"""Harness boundary: the ONLY module that changes when the real harness
contract lands.

Reads tasks from `/input/tasks.json` (default), with fallback to `--input`/
`--output` CLI args or stdin JSON. Writes `{id, output}` pairs to
`/output/results.json` (or `--output`) and logs a run summary (tokens by
tier, route distribution) to stderr — never into the results file.

All actual solving logic lives in `router.py`; this module only handles I/O,
schema tolerance, and summary logging.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, TextIO

from routing_agent.client import FireworksClient, TokenLedger
from routing_agent.config import Settings, load_policy
from routing_agent.models import Task
from routing_agent.registry import KNOWN_MODELS, resolve_allowed
from routing_agent.router import route

logger = logging.getLogger(__name__)

DEFAULT_INPUT_PATH = "/input/tasks.json"
DEFAULT_OUTPUT_PATH = "/output/results.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="routing_agent.adapter",
        description="Run the routing agent over a tasks.json file.",
    )
    parser.add_argument(
        "--input",
        default=None,
        help=f"Path to tasks.json (default: {DEFAULT_INPUT_PATH}, or stdin if absent).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"Path to write results.json (default: {DEFAULT_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--policy",
        default=None,
        help="Path to a routing policy YAML (default: built-in policy defaults).",
    )
    return parser.parse_args(argv)


def _read_tasks(input_path: str | None, stdin: TextIO) -> list[dict[str, Any]]:
    """Load raw task dicts from a file path, the default input path, or stdin.

    Resolution order: explicit --input path -> DEFAULT_INPUT_PATH (if it
    exists) -> stdin. Raises ValueError on malformed JSON or a non-list
    top-level payload, so failures surface immediately rather than producing
    a silently empty results.json.
    """
    if input_path is not None:
        raw_text = Path(input_path).read_text(encoding="utf-8")
    elif Path(DEFAULT_INPUT_PATH).exists():
        raw_text = Path(DEFAULT_INPUT_PATH).read_text(encoding="utf-8")
    else:
        raw_text = stdin.read()

    if not raw_text.strip():
        raise ValueError("no task input provided (empty file/stdin)")

    parsed = json.loads(raw_text)
    if not isinstance(parsed, list):
        raise ValueError("tasks.json must contain a top-level JSON array")
    return parsed


def _parse_tasks(raw_tasks: list[dict[str, Any]]) -> list[Task]:
    tasks: list[Task] = []
    for index, raw_task in enumerate(raw_tasks):
        if "id" not in raw_task:
            raw_task = {**raw_task, "id": str(index)}
        tasks.append(Task.model_validate(raw_task))
    return tasks


def run(
    tasks: list[Task],
    settings: Settings,
    policy_path: str | None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Route every task and return (results, summary).

    `results` is the harness-facing payload: only `id` and `output` per task.
    `summary` is diagnostic-only (route distribution, token totals by tier)
    and must never be written into the results file.
    """
    policy = load_policy(policy_path)
    allowed_models = resolve_allowed(settings.allowed_models)
    ledger = TokenLedger()
    client = FireworksClient(
        api_key=settings.fireworks_api_key,
        base_url=settings.fireworks_base_url,
        ledger=ledger,
    )

    results: list[dict[str, str]] = []
    tier_counts: Counter[int] = Counter()
    task_type_counts: Counter[str] = Counter()

    for task in tasks:
        outcome = route(task, client, allowed_models, policy)
        results.append({"id": task.id, "output": outcome.output})
        tier_counts[outcome.route.tier] += 1
        task_type_counts[outcome.route.task_type] += 1

    price_models = {m.id: m for m in allowed_models} | KNOWN_MODELS
    summary = {
        "total_tasks": len(tasks),
        "tier_distribution": dict(tier_counts),
        "task_type_distribution": dict(task_type_counts),
        "total_raw_tokens": ledger.total_raw_tokens,
        "total_price_weighted_usd": round(ledger.total_price_weighted(price_models), 6),
        "total_calls": len(ledger.records),
        "retried_calls": sum(1 for r in ledger.records if r.retry),
    }
    return results, summary


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = parse_args(argv)

    try:
        raw_tasks = _read_tasks(args.input, sys.stdin)
        tasks = _parse_tasks(raw_tasks)
        settings = Settings.from_env()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        logger.error("adapter startup failed: %s", exc)
        return 1

    results, summary = run(tasks, settings, args.policy)

    output_path = Path(args.output or DEFAULT_OUTPUT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    logger.info("run summary: %s", json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
