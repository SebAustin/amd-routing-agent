"""Eval runner: routes evals/evalset/*.jsonl through the router under a named
policy, grades each answer, and reports accuracy/token/route-distribution
metrics (PLAN.md §3 evals).

Modes:
    --dry-run    No network calls. Tier-0 solvers + classifier only; any task
                 that would need a model call is answered "" and recorded as
                 "would-call:<tier1-model-id>" (or "would-call:none" if no
                 model is allowed for its capability). Lets us measure
                 Tier-0/classifier coverage for free.
    (default)    Full cascade against the real Fireworks API.
    --baseline   Every task goes straight to the strongest allowed model with
                 a generic prompt ("Answer the following.") and
                 max_tokens=512 — the SC2 comparison bar.

Usage:
    uv run python evals/run_eval.py --policy default
    uv run python evals/run_eval.py --policy default --dry-run
    uv run python evals/run_eval.py --policy default --categories arithmetic,dates
    uv run python evals/run_eval.py --baseline --limit 60 --stratified
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_REPO_ROOT_FOR_IMPORTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORTS / "src"))
sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORTS / "evals"))

from env_loader import load_dotenv  # noqa: E402
from graders import grade, iter_evalset  # noqa: E402

from routing_agent.classifier import classify  # noqa: E402
from routing_agent.client import FireworksClient, TokenLedger  # noqa: E402
from routing_agent.config import Settings, load_policy  # noqa: E402
from routing_agent.models import Task  # noqa: E402
from routing_agent.registry import (  # noqa: E402
    KNOWN_MODELS,
    ModelInfo,
    cheapest,
    resolve_allowed,
    strongest,
)
from routing_agent.router import _CAPABILITY_BY_TYPE, _try_tier0, route  # noqa: E402

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALSET_DIR = REPO_ROOT / "evals" / "evalset"
POLICIES_DIR = REPO_ROOT / "evals" / "policies"
REPORTS_DIR = REPO_ROOT / "evals" / "reports"

_DEFAULT_ALLOWED_MODELS = (
    "accounts/fireworks/models/gpt-oss-20b,"
    "accounts/fireworks/models/gpt-oss-120b,"
    "accounts/fireworks/models/deepseek-v4-flash,"
    "accounts/fireworks/models/deepseek-v4-pro,"
    "accounts/fireworks/models/glm-5p1"
)
_BASELINE_PROMPT = "Answer the following."
_BASELINE_MAX_TOKENS = 512
_CONCURRENCY = 8
_STRATIFIED_SEED = 42


class EvalTask:
    """One evalset task plus its grading spec, paired with a routable `Task`."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.id: str = raw["id"]
        self.category: str = raw["category"]
        self.prompt: str = raw["prompt"]
        self.expected: str = raw["expected"]
        self.grader: str = raw["grader"]
        self.grader_args: dict[str, Any] = raw.get("grader_args", {})
        self.task = Task(id=self.id, prompt=self.prompt)


def load_tasks(categories: list[str] | None = None) -> list[EvalTask]:
    """Load every task from evals/evalset, optionally filtered to `categories`."""
    tasks = [EvalTask(raw) for raw in iter_evalset(EVALSET_DIR)]
    if categories:
        wanted = set(categories)
        tasks = [t for t in tasks if t.category in wanted]
    return tasks


def stratified_subset(
    tasks: list[EvalTask], limit: int, seed: int = _STRATIFIED_SEED
) -> list[EvalTask]:
    """Pick ~`limit` tasks preserving each category's proportional share.

    Deterministic given `seed`. Every category with at least one task
    contributes at least one sample (rounding favors coverage over exact
    proportionality on tiny categories like summarization's 5 tasks).
    """
    by_category: dict[str, list[EvalTask]] = defaultdict(list)
    for t in tasks:
        by_category[t.category].append(t)

    rng = random.Random(seed)
    total = len(tasks)
    subset: list[EvalTask] = []
    for _category, items in sorted(by_category.items()):
        share = max(1, round(limit * len(items) / total))
        shuffled = items[:]
        rng.shuffle(shuffled)
        subset.extend(shuffled[:share])
    return subset[:limit] if len(subset) > limit else subset


def _resolve_settings() -> Settings:
    """Build Settings from the environment, applying the documented default
    ALLOWED_MODELS (evals/README.md) when the env var is unset — keeps local
    eval runs reproducible without requiring every operator to export it.
    """
    load_dotenv(REPO_ROOT / ".env")
    import os

    if not os.environ.get("ALLOWED_MODELS"):
        os.environ["ALLOWED_MODELS"] = _DEFAULT_ALLOWED_MODELS
    return Settings.from_env()


def _would_call_result(eval_task: EvalTask, allowed_models: list[ModelInfo]) -> tuple[str, str]:
    """Dry-run stand-in for a Tier-1/Tier-2 model call: returns
    (output, route_label) without touching the network.
    """
    task_type = classify(eval_task.prompt)
    capability = _CAPABILITY_BY_TYPE.get(task_type, "general")
    model = cheapest(capability, allowed_models)
    if model is None:
        return "", "would-call:none"
    return "", f"would-call:{model.id}"


def _run_dry_run_task(eval_task: EvalTask, allowed_models: list[ModelInfo]) -> dict[str, Any]:
    task_type = classify(eval_task.prompt)
    tier0_result = _try_tier0(eval_task.task, task_type)
    if tier0_result.confident and tier0_result.answer is not None:
        correct = grade(
            eval_task.expected, tier0_result.answer, eval_task.grader, eval_task.grader_args
        )
        return {
            "id": eval_task.id,
            "category": eval_task.category,
            "task_type": task_type.value,
            "route": "tier0",
            "output": tier0_result.answer,
            "correct": correct,
            "error": None,
        }

    output, route_label = _would_call_result(eval_task, allowed_models)
    return {
        "id": eval_task.id,
        "category": eval_task.category,
        "task_type": task_type.value,
        "route": route_label,
        "output": output,
        "correct": False,
        "error": None,
    }


def _run_live_task(
    eval_task: EvalTask,
    client: FireworksClient,
    allowed_models: list[ModelInfo],
    policy,
) -> dict[str, Any]:
    calls_before = len(client.ledger.records)
    try:
        result = route(eval_task.task, client, allowed_models, policy)
        output = result.output
        route_decision = result.route
        error = None
    except Exception as exc:  # noqa: BLE001 - isolate one task's failure from the run
        logger.warning("task %s failed: %s", eval_task.id, exc)
        output = ""
        route_decision = None
        error = str(exc)

    correct = (
        grade(eval_task.expected, output, eval_task.grader, eval_task.grader_args)
        if error is None
        else False
    )
    calls_made = len(client.ledger.records) - calls_before
    if route_decision is None:
        route_label = "error"
    elif route_decision.tier == 0:
        route_label = "tier0"
    else:
        route_label = f"tier{route_decision.tier}:{route_decision.model or 'none'}"

    return {
        "id": eval_task.id,
        "category": eval_task.category,
        "task_type": route_decision.task_type
        if route_decision
        else classify(eval_task.prompt).value,
        "route": route_label,
        "retried": route_decision.retried if route_decision else False,
        "escalated": route_decision.escalated if route_decision else False,
        "output": output,
        "correct": correct,
        "error": error,
        "calls_made": calls_made,
    }


def _run_baseline_task(
    eval_task: EvalTask,
    client: FireworksClient,
    strongest_model: ModelInfo,
) -> dict[str, Any]:
    try:
        completion = client.complete(
            model_info=strongest_model,
            messages=[{"role": "user", "content": f"{_BASELINE_PROMPT}\n\n{eval_task.prompt}"}],
            max_tokens=_BASELINE_MAX_TOKENS,
            route=f"baseline:{eval_task.id}",
            # A naive/untuned deployment would not carry our registry's
            # reasoning-suppression profile — this must be the true
            # comparison bar for SC2, not a hybrid of "generic prompt" +
            # "our own tuning". See client.py's `apply_reasoning_profile`.
            apply_reasoning_profile=False,
        )
        output = completion.content.strip()
        error = None
    except Exception as exc:  # noqa: BLE001
        logger.warning("baseline task %s failed: %s", eval_task.id, exc)
        output = ""
        error = str(exc)

    correct = (
        grade(eval_task.expected, output, eval_task.grader, eval_task.grader_args)
        if error is None
        else False
    )
    return {
        "id": eval_task.id,
        "category": eval_task.category,
        "route": f"baseline:{strongest_model.id}",
        "output": output,
        "correct": correct,
        "error": error,
    }


def run_dry_run(tasks: list[EvalTask], allowed_models: list[ModelInfo]) -> dict[str, Any]:
    results = [_run_dry_run_task(t, allowed_models) for t in tasks]
    return _summarize(results, mode="dry-run")


def run_live(
    tasks: list[EvalTask], settings: Settings, policy, concurrency: int = _CONCURRENCY
) -> dict[str, Any]:
    allowed_models = resolve_allowed(settings.allowed_models)
    ledger = TokenLedger()
    client = FireworksClient(
        api_key=settings.fireworks_api_key,
        base_url=settings.fireworks_base_url,
        ledger=ledger,
    )

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_run_live_task, t, client, allowed_models, policy): t for t in tasks}
        for future in as_completed(futures):
            results.append(future.result())

    summary = _summarize(results, mode="live")
    price_models = {m.id: m for m in allowed_models} | KNOWN_MODELS
    summary["total_raw_tokens"] = ledger.total_raw_tokens
    summary["total_prompt_tokens"] = sum(r.prompt_tokens for r in ledger.records)
    summary["total_completion_tokens"] = sum(r.completion_tokens for r in ledger.records)
    summary["total_price_weighted_usd"] = round(ledger.total_price_weighted(price_models), 6)
    summary["total_calls"] = len(ledger.records)
    summary["retried_calls"] = sum(1 for r in ledger.records if r.retry)
    summary["retry_rate"] = (
        round(summary["retried_calls"] / summary["total_calls"], 4)
        if summary["total_calls"]
        else 0.0
    )
    return summary


def run_baseline(
    tasks: list[EvalTask], settings: Settings, concurrency: int = _CONCURRENCY
) -> dict[str, Any]:
    allowed_models = resolve_allowed(settings.allowed_models)
    strongest_model = strongest(allowed_models)
    if strongest_model is None:
        raise ValueError("no allowed models available for baseline run")

    ledger = TokenLedger()
    client = FireworksClient(
        api_key=settings.fireworks_api_key,
        base_url=settings.fireworks_base_url,
        ledger=ledger,
    )

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_run_baseline_task, t, client, strongest_model): t for t in tasks}
        for future in as_completed(futures):
            results.append(future.result())

    summary = _summarize(results, mode="baseline")
    price_models = {m.id: m for m in allowed_models} | KNOWN_MODELS
    summary["total_raw_tokens"] = ledger.total_raw_tokens
    summary["total_prompt_tokens"] = sum(r.prompt_tokens for r in ledger.records)
    summary["total_completion_tokens"] = sum(r.completion_tokens for r in ledger.records)
    summary["total_price_weighted_usd"] = round(ledger.total_price_weighted(price_models), 6)
    summary["total_calls"] = len(ledger.records)
    summary["tokens_per_task"] = (
        round(summary["total_raw_tokens"] / len(tasks), 2) if tasks else 0.0
    )
    summary["baseline_model"] = strongest_model.id
    summary["sample_size"] = len(tasks)
    return summary


def _summarize(results: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    by_category: dict[str, dict[str, Any]] = {}
    for category in sorted({r["category"] for r in results}):
        cat_results = [r for r in results if r["category"] == category]
        cat_correct = sum(1 for r in cat_results if r["correct"])
        by_category[category] = {
            "total": len(cat_results),
            "correct": cat_correct,
            "accuracy": round(cat_correct / len(cat_results), 4) if cat_results else 0.0,
        }

    route_distribution = Counter(r["route"] for r in results)
    zero_token_routes = sum(
        1 for r in results if r["route"] == "tier0" or r["route"].startswith("would-call")
    )
    errors = [r for r in results if r.get("error")]

    return {
        "mode": mode,
        "total_tasks": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "by_category": by_category,
        "route_distribution": dict(route_distribution),
        "zero_token_tasks": zero_token_routes,
        "zero_token_rate": round(zero_token_routes / total, 4) if total else 0.0,
        "error_count": len(errors),
        "errors": [{"id": e["id"], "error": e["error"]} for e in errors][:20],
        "results": results,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the routing agent eval suite.")
    parser.add_argument("--policy", default="default", help="Policy name under evals/policies/.")
    parser.add_argument("--categories", default=None, help="Comma-separated category filter.")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of tasks.")
    parser.add_argument(
        "--stratified",
        action="store_true",
        help="With --limit, sample proportionally across categories instead of truncating.",
    )
    parser.add_argument("--dry-run", action="store_true", help="No network; Tier-0 only.")
    parser.add_argument(
        "--baseline", action="store_true", help="Strongest-model-only comparison run."
    )
    parser.add_argument(
        "--concurrency", type=int, default=_CONCURRENCY, help="Thread pool size for live calls."
    )
    parser.add_argument(
        "--no-report", action="store_true", help="Skip writing a JSON report to evals/reports/."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    args = parse_args(argv)

    categories = args.categories.split(",") if args.categories else None
    tasks = load_tasks(categories)
    if args.limit is not None:
        tasks = stratified_subset(tasks, args.limit) if args.stratified else tasks[: args.limit]

    if not tasks:
        print("No tasks matched the given filters.", file=sys.stderr)
        return 1

    started = time.monotonic()

    if args.dry_run:
        settings = _resolve_settings()
        allowed_models = resolve_allowed(settings.allowed_models)
        summary = run_dry_run(tasks, allowed_models)
        mode_label = "dry-run"
    elif args.baseline:
        settings = _resolve_settings()
        summary = run_baseline(tasks, settings, concurrency=args.concurrency)
        mode_label = "baseline"
    else:
        settings = _resolve_settings()
        policy_path = POLICIES_DIR / f"{args.policy}.yaml"
        policy = load_policy(policy_path)
        summary = run_live(tasks, settings, policy, concurrency=args.concurrency)
        mode_label = "live"

    elapsed_s = round(time.monotonic() - started, 2)
    summary["policy"] = args.policy
    summary["elapsed_s"] = elapsed_s

    _print_report(summary)

    if not args.no_report:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORTS_DIR / f"{args.policy}-{mode_label}.json"
        # Reports are committed as evidence; keep them small by trimming the
        # full per-task results list to essentials in the persisted file.
        persisted = dict(summary)
        persisted["results"] = [
            {k: v for k, v in r.items() if k != "output"} for r in summary["results"]
        ]
        report_path.write_text(json.dumps(persisted, indent=2), encoding="utf-8")
        print(f"\nReport written to {report_path.relative_to(REPO_ROOT)}", file=sys.stderr)

    return 0


def _print_report(summary: dict[str, Any]) -> None:
    total = summary["total_tasks"]
    correct = summary["correct"]
    accuracy_pct = summary["accuracy"] * 100

    print(f"\n=== Eval report: mode={summary['mode']} policy={summary.get('policy')} ===")
    print(f"Total tasks: {total}   Elapsed: {summary.get('elapsed_s')}s")
    print(f"Overall accuracy: {accuracy_pct:.1f}% ({correct}/{total})")

    print("\nPer-category accuracy:")
    for category, stats in summary["by_category"].items():
        cat_pct = stats["accuracy"] * 100
        print(f"  {category:<16} {cat_pct:5.1f}%  ({stats['correct']}/{stats['total']})")

    zero_pct = summary["zero_token_rate"] * 100
    print(f"\nZero-token tasks: {summary['zero_token_tasks']} ({zero_pct:.1f}%)")

    print("\nRoute distribution:")
    for route_key, count in sorted(summary["route_distribution"].items()):
        print(f"  {route_key:<50} {count}")

    if "total_raw_tokens" in summary:
        prompt_tok = summary.get("total_prompt_tokens")
        completion_tok = summary.get("total_completion_tokens")
        retried = summary.get("retried_calls", "n/a")
        print(f"\nTotal raw tokens: {summary['total_raw_tokens']}")
        print(f"  prompt: {prompt_tok}  completion: {completion_tok}")
        print(f"Total price-weighted cost: ${summary['total_price_weighted_usd']:.6f}")
        print(f"Total calls: {summary['total_calls']}  Retried: {retried}")

    if summary["error_count"]:
        print(f"\n{summary['error_count']} task(s) errored (showing up to 20):")
        for err in summary["errors"]:
            print(f"  {err['id']}: {err['error']}")


if __name__ == "__main__":
    raise SystemExit(main())
