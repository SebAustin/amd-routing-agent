"""FastAPI demo app: interactive dashboard for the routing cascade.

This module is judge-facing packaging, not scoring logic — it reuses
`router.route()` unchanged and layers a small HTTP surface + inline HTML
dashboard on top:

  POST /solve      -> run one prompt through the cascade, report route +
                       tokens + cost + savings vs a baseline estimate.
  GET  /api/stats   -> cumulative TokenLedger stats across this process's
                       lifetime (route distribution, totals, savings).
  GET  /healthz     -> liveness probe.
  GET  /            -> self-contained HTML/CSS/JS dashboard (no CDNs).

Demo-mode contract: if `FIREWORKS_API_KEY` is unset at startup, the app
still boots. Tier-0 tasks (arithmetic, dates, strings, units, extraction)
keep working with zero tokens; any task that would need a model call
returns a 503 with a clear "demo mode" message instead of crashing.

Public-demo hardening (SECURITY.md M-2): a public Space URL is
unauthenticated by design, so two in-memory guards protect the shared
Fireworks key from being scripted into a large bill —
  1. a per-IP sliding-window rate limit on POST /solve (429 on burst), and
  2. a global daily spend cap tracked from the same TokenLedger used for
     the stats dashboard (503 for model-path requests once exceeded;
     Tier-0 keeps working since it costs nothing).
Both are single-process, in-memory state — correct for the one-process
demo deployment this app ships as; not a substitute for a real auth/quota
layer if this ever needs to scale beyond a single demo instance.
"""

from __future__ import annotations

import logging
import os
import time
from collections import Counter, deque
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from routing_agent.classifier import classify
from routing_agent.client import FireworksClient, TokenLedger
from routing_agent.config import Policy, Settings, load_policy
from routing_agent.models import Task
from routing_agent.registry import KNOWN_MODELS, ModelInfo, resolve_allowed, strongest
from routing_agent.router import route

logger = logging.getLogger(__name__)

# Rate limit: requests per IP per rolling 60s window. Env-tunable so the
# operator can raise/lower it per deployment without a code change.
_DEFAULT_RATE_LIMIT_PER_MIN = 10
_RATE_LIMIT_WINDOW_SECONDS = 60.0

# Daily spend cap in USD, price-weighted (TokenLedger.total_price_weighted).
# Tier-0 answers are always free and never count against this cap.
_DEFAULT_DEMO_DAILY_BUDGET_USD = 1.00

# Heuristic baseline: what the strongest allowed model would have cost on
# this exact prompt with a "default" (unoptimized) 512-token cap, i.e. the
# naive "always use the biggest model, don't tune max_tokens" policy this
# project is competing against (PLAN.md SC2). Estimated, not measured,
# because computing it for real would double every model call.
_BASELINE_DEFAULT_MAX_TOKENS = 512
_CHARS_PER_TOKEN_ESTIMATE = 4


class SolveRequest(BaseModel):
    """Request body for POST /solve."""

    prompt: str = Field(min_length=1, max_length=8000)


def _client_ip(request: Request) -> str:
    """Best-effort client identity for rate limiting.

    Spaces (and most PaaS front doors) terminate TLS at a proxy and forward
    the real client address in `X-Forwarded-For`; honor the *first* address
    in that list (the original client) since later entries are proxies in
    the chain. Falls back to the direct peer address when the header is
    absent (local/dev runs, direct `docker run`).
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


class SlidingWindowRateLimiter:
    """Per-key sliding-window request counter, stdlib only.

    Correct (not approximate) sliding window: keeps each key's recent
    request timestamps in a deque and evicts anything older than the
    window on every check, so a burst can't straddle two fixed buckets to
    double the effective limit. In-memory only — fine for a single-process
    demo; would need a shared store (Redis, etc.) behind a load balancer.
    """

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        """Record one request attempt for `key`; return False if it would
        exceed `limit` requests within the trailing `window_seconds`.
        """
        now = now if now is not None else time.monotonic()
        bucket = self._hits.setdefault(key, deque())
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


class DailyBudgetTracker:
    """Tracks cumulative price-weighted spend for the current UTC day.

    Resets automatically on UTC day rollover (checked lazily on each
    `spent_today` / `record` call — no background timer needed). Backed by
    the same TokenLedger the stats endpoint already reads, so this adds no
    duplicate bookkeeping: it just remembers where in the ledger "today"
    started.
    """

    def __init__(self, budget_usd: float) -> None:
        self.budget_usd = budget_usd
        self._day: str = self._today()
        self._records_at_day_start = 0

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def _roll_if_new_day(self, ledger: TokenLedger) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            self._records_at_day_start = len(ledger.records)

    def spent_today_usd(self, ledger: TokenLedger, price_models: dict[str, ModelInfo]) -> float:
        self._roll_if_new_day(ledger)
        todays_records = ledger.records[self._records_at_day_start :]
        todays_ledger = TokenLedger(records=list(todays_records))
        return todays_ledger.total_price_weighted(price_models)

    def is_exceeded(self, ledger: TokenLedger, price_models: dict[str, ModelInfo]) -> bool:
        return self.spent_today_usd(ledger, price_models) >= self.budget_usd


def _estimate_prompt_tokens(text: str, overhead: int) -> int:
    """Cheap, dependency-free token estimate (chars/4 + chat-template overhead).

    Used only for the baseline comparison figure, never for real routing
    decisions — actual routing always uses live `usage` from the API.
    """
    return overhead + max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


def _baseline_estimate_tokens(prompt_text: str, allowed_models: list[ModelInfo]) -> int:
    """Estimate tokens the naive baseline policy would have spent on this
    prompt: strongest allowed model, default prompt (no system message, no
    per-type max_tokens tuning), fixed 512-token completion cap.
    """
    baseline_model = strongest(allowed_models) or KNOWN_MODELS.get(
        "accounts/fireworks/models/deepseek-v4-pro"
    )
    overhead = baseline_model.prompt_overhead_tokens if baseline_model else 20
    prompt_tokens = _estimate_prompt_tokens(prompt_text, overhead)
    return prompt_tokens + _BASELINE_DEFAULT_MAX_TOKENS


def _price_models(allowed_models: list[ModelInfo]) -> dict[str, ModelInfo]:
    return {m.id: m for m in allowed_models} | KNOWN_MODELS


class AppState:
    """Process-lifetime demo state: settings, resolved models, and a single
    shared `TokenLedger` so /api/stats can report cumulative savings across
    every /solve call served by this process.
    """

    def __init__(self) -> None:
        self.demo_mode = False
        self.settings: Settings | None = None
        self.allowed_models: list[ModelInfo] = []
        self.policy: Policy = load_policy(os.environ.get("ROUTING_POLICY_PATH"))
        self.ledger = TokenLedger()
        self.client: FireworksClient | None = None
        self.baseline_total_tokens = 0
        self.solved_count = 0

        rate_limit_per_min = int(
            os.environ.get("RATE_LIMIT_PER_MIN", str(_DEFAULT_RATE_LIMIT_PER_MIN))
        )
        self.rate_limiter = SlidingWindowRateLimiter(
            limit=rate_limit_per_min, window_seconds=_RATE_LIMIT_WINDOW_SECONDS
        )

        daily_budget_usd = float(
            os.environ.get("DEMO_DAILY_BUDGET_USD", str(_DEFAULT_DEMO_DAILY_BUDGET_USD))
        )
        self.budget_tracker = DailyBudgetTracker(budget_usd=daily_budget_usd)

        try:
            self.settings = Settings.from_env()
        except ValueError:
            logger.warning("FIREWORKS_API_KEY not set — starting in demo mode (Tier-0 only)")
            self.demo_mode = True
            return

        self.allowed_models = resolve_allowed(self.settings.allowed_models)
        self.client = FireworksClient(
            api_key=self.settings.fireworks_api_key,
            base_url=self.settings.fireworks_base_url,
            ledger=self.ledger,
        )

    def needs_model(self, prompt_text: str) -> bool:
        """True if this prompt cannot be resolved by a Tier-0 solver alone,
        i.e. it would require a Fireworks call.
        """
        from routing_agent.router import _try_tier0

        task_type = classify(prompt_text)
        tier0_result = _try_tier0(Task(id="probe", prompt=prompt_text), task_type)
        return not (tier0_result.confident and tier0_result.answer is not None)


app = FastAPI(title="Routing Agent Demo", version="0.1.0")
state = AppState()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/solve")
def solve(request: SolveRequest, http_request: Request) -> JSONResponse:
    """Run one prompt through the Tier 0/1/2 cascade and report the route,
    tokens, cost, and savings vs the naive baseline estimate.

    Two demo-safety gates run before any model call (SECURITY.md M-2):
      1. per-IP sliding-window rate limit -> 429 on burst.
      2. global daily spend cap -> 503 once exceeded, but only for prompts
         that would actually need a paid model call; Tier-0 stays free and
         keeps working regardless of budget state.
    """
    client_ip = _client_ip(http_request)
    if not state.rate_limiter.allow(client_ip):
        raise HTTPException(
            status_code=429,
            detail=(
                f"rate limit exceeded: max {state.rate_limiter.limit} requests "
                "per minute per client. Please slow down and try again shortly."
            ),
        )

    prompt_text = request.prompt.strip()
    if not prompt_text:
        raise HTTPException(status_code=422, detail="prompt must not be empty")

    if state.demo_mode and state.needs_model(prompt_text):
        raise HTTPException(
            status_code=503,
            detail=(
                "demo mode: no API key configured — this prompt needs a model call. "
                "Set FIREWORKS_API_KEY to enable Tier-1/Tier-2 routing."
            ),
        )

    if not state.demo_mode and state.needs_model(prompt_text):
        price_models = _price_models(state.allowed_models)
        if state.budget_tracker.is_exceeded(state.ledger, price_models):
            raise HTTPException(
                status_code=503,
                detail="demo budget reached for today — please try again tomorrow.",
            )

    task = Task(id=f"demo-{int(time.time() * 1000)}", prompt=prompt_text)
    calls_before = len(state.ledger.records)

    outcome = route(task, state.client, state.allowed_models, state.policy)

    new_calls = state.ledger.records[calls_before:]
    prompt_tokens = sum(c.prompt_tokens for c in new_calls)
    completion_tokens = sum(c.completion_tokens for c in new_calls)
    total_tokens = prompt_tokens + completion_tokens

    price_models = _price_models(state.allowed_models)
    cost_usd = round(
        sum(
            (c.prompt_tokens / 1_000_000) * price_models[c.model].price_in
            + (c.completion_tokens / 1_000_000) * price_models[c.model].price_out
            for c in new_calls
            if c.model in price_models
        ),
        6,
    )

    baseline_tokens = _baseline_estimate_tokens(prompt_text, state.allowed_models)
    savings_pct = round(100.0 * (1 - total_tokens / baseline_tokens), 2) if baseline_tokens else 0.0

    state.baseline_total_tokens += baseline_tokens
    state.solved_count += 1

    return JSONResponse(
        {
            "answer": outcome.output,
            "route": {
                "tier": outcome.route.tier,
                "model": outcome.route.model,
                "task_type": outcome.route.task_type,
            },
            "tokens": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total_tokens,
            },
            "cost_usd": cost_usd,
            "baseline_estimate_tokens": baseline_tokens,
            "savings_pct": savings_pct,
        }
    )


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    """Cumulative TokenLedger stats across every /solve call this process
    has served: totals, route distribution, and savings vs the running sum
    of per-request baseline estimates.
    """
    tier_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()
    for record in state.ledger.records:
        model_counts[record.model] += 1

    # Route (tier) distribution isn't stored on CallRecord directly; derive
    # from the `route` field prefix ("tier1:...", "tier2:...") that
    # router.py stamps on every client.complete() call.
    for record in state.ledger.records:
        tier_label = record.route.split(":", 1)[0] if record.route else "unknown"
        tier_counts[tier_label] += 1

    price_models = _price_models(state.allowed_models)
    total_raw_tokens = state.ledger.total_raw_tokens
    total_cost_usd = round(state.ledger.total_price_weighted(price_models), 6)

    savings_pct = 0.0
    if state.baseline_total_tokens:
        savings_pct = round(100.0 * (1 - total_raw_tokens / state.baseline_total_tokens), 2)

    return {
        "demo_mode": state.demo_mode,
        "solved_count": state.solved_count,
        "total_calls": len(state.ledger.records),
        "total_raw_tokens": total_raw_tokens,
        "total_cost_usd": total_cost_usd,
        "baseline_estimate_tokens": state.baseline_total_tokens,
        "savings_pct": savings_pct,
        "tier_call_distribution": dict(tier_counts),
        "model_call_distribution": dict(model_counts),
    }


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    """Self-contained inline HTML dashboard — no external CDNs, no build
    step. Vanilla JS polls /solve on submit and /api/stats after each call.
    """
    return _DASHBOARD_HTML


_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Routing Agent — Token-Efficient Cascade Demo</title>
<style>
  :root {
    --color-bg: #0b0b0d;
    --color-surface: #141416;
    --color-surface-raised: #1c1c1f;
    --color-border: #2a2a2e;
    --color-text: #ececee;
    --color-text-dim: #8b8b92;
    --color-accent: #ED1C24;
    --color-accent-dim: #7a1013;
    --color-tier0: #2fbf71;
    --color-tier1: #ffb020;
    --color-tier2: #ED1C24;
    --mono: "SF Mono", "JetBrains Mono", "Fira Code", ui-monospace, Menlo, Consolas, monospace;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Helvetica, Arial, sans-serif;
    --duration-fast: 150ms;
    --duration-normal: 300ms;
    --ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--color-bg);
    background-image:
      radial-gradient(circle at 15% 10%, rgba(237, 28, 36, 0.08), transparent 40%),
      radial-gradient(circle at 85% 90%, rgba(237, 28, 36, 0.05), transparent 45%);
    color: var(--color-text);
    font-family: var(--sans);
    min-height: 100vh;
    line-height: 1.5;
  }

  header {
    padding: 2.5rem clamp(1.25rem, 4vw, 3rem) 1.5rem;
    border-bottom: 1px solid var(--color-border);
  }

  .brand {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
  }

  .brand-mark {
    width: 0.9rem;
    height: 0.9rem;
    background: var(--color-accent);
    border-radius: 2px;
    flex-shrink: 0;
    box-shadow: 0 0 18px rgba(237, 28, 36, 0.55);
  }

  h1 {
    font-size: clamp(1.4rem, 2.4vw, 1.9rem);
    font-weight: 700;
    margin: 0;
    letter-spacing: -0.01em;
  }

  header p {
    color: var(--color-text-dim);
    margin: 0.4rem 0 0 1.65rem;
    font-size: 0.92rem;
    max-width: 62ch;
  }

  main {
    padding: 2rem clamp(1.25rem, 4vw, 3rem) 4rem;
    display: grid;
    grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr);
    gap: 1.5rem;
    max-width: 1280px;
    margin: 0 auto;
  }

  @media (max-width: 860px) {
    main { grid-template-columns: 1fr; }
  }

  section.panel {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 14px;
    padding: 1.5rem;
  }

  .panel h2 {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--color-text-dim);
    margin: 0 0 1rem;
    font-weight: 600;
  }

  textarea {
    width: 100%;
    min-height: 110px;
    resize: vertical;
    background: var(--color-surface-raised);
    border: 1px solid var(--color-border);
    border-radius: 10px;
    color: var(--color-text);
    padding: 0.85rem;
    font-family: var(--sans);
    font-size: 0.95rem;
    transition: border-color var(--duration-fast) var(--ease-out-expo);
  }

  textarea:focus {
    outline: none;
    border-color: var(--color-accent);
  }

  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 0.9rem;
    gap: 0.75rem;
  }

  .examples {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }

  .chip {
    background: transparent;
    border: 1px solid var(--color-border);
    color: var(--color-text-dim);
    border-radius: 999px;
    padding: 0.3rem 0.7rem;
    font-size: 0.76rem;
    cursor: pointer;
    transition: border-color var(--duration-fast) var(--ease-out-expo),
                color var(--duration-fast) var(--ease-out-expo);
  }

  .chip:hover { border-color: var(--color-accent); color: var(--color-text); }

  button.submit {
    background: var(--color-accent);
    color: #fff;
    border: none;
    border-radius: 10px;
    padding: 0.7rem 1.4rem;
    font-weight: 600;
    font-size: 0.9rem;
    cursor: pointer;
    transition: transform var(--duration-fast) var(--ease-out-expo),
                background var(--duration-fast) var(--ease-out-expo);
    flex-shrink: 0;
  }

  button.submit:hover:not(:disabled) { background: #ff363e; transform: translateY(-1px); }
  button.submit:active:not(:disabled) { transform: translateY(0); }
  button.submit:disabled { background: var(--color-accent-dim); cursor: not-allowed; opacity: 0.6; }
  button.submit:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }

  .answer-box {
    margin-top: 1.25rem;
    background: var(--color-surface-raised);
    border: 1px solid var(--color-border);
    border-radius: 10px;
    padding: 1rem;
    min-height: 3.2rem;
    font-family: var(--mono);
    font-size: 0.92rem;
    white-space: pre-wrap;
    word-break: break-word;
    opacity: 0;
    transform: translateY(4px);
    transition: opacity var(--duration-normal) var(--ease-out-expo),
                transform var(--duration-normal) var(--ease-out-expo);
  }

  .answer-box.visible { opacity: 1; transform: translateY(0); }

  .error-box {
    margin-top: 1rem;
    border: 1px solid var(--color-accent-dim);
    background: rgba(237, 28, 36, 0.08);
    color: #ffb3b6;
    border-radius: 10px;
    padding: 0.85rem 1rem;
    font-size: 0.85rem;
    display: none;
  }

  .error-box.visible { display: block; }

  .route-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem;
    margin-top: 1rem;
  }

  .route-card {
    background: var(--color-surface-raised);
    border: 1px solid var(--color-border);
    border-radius: 10px;
    padding: 0.8rem;
  }

  .route-card .label {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--color-text-dim);
    margin-bottom: 0.3rem;
  }

  .route-card .value {
    font-family: var(--mono);
    font-size: 1rem;
    font-weight: 600;
  }

  .tier-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-family: var(--mono);
    font-weight: 700;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    font-size: 0.8rem;
  }

  .tier-badge.tier-0 { background: rgba(47, 191, 113, 0.15); color: var(--color-tier0); }
  .tier-badge.tier-1 { background: rgba(255, 176, 32, 0.15); color: var(--color-tier1); }
  .tier-badge.tier-2 { background: rgba(237, 28, 36, 0.15); color: var(--color-tier2); }

  .stat-list { display: flex; flex-direction: column; gap: 0.9rem; }

  .stat-item {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    border-bottom: 1px dashed var(--color-border);
    padding-bottom: 0.7rem;
  }

  .stat-item:last-child { border-bottom: none; padding-bottom: 0; }

  .stat-item .stat-label { color: var(--color-text-dim); font-size: 0.85rem; }

  .stat-item .stat-value {
    font-family: var(--mono);
    font-size: 1.15rem;
    font-weight: 700;
  }

  .stat-value.accent { color: var(--color-accent); }
  .stat-value.good { color: var(--color-tier0); }

  .bar-wrap { margin-top: 1.5rem; }

  .bar-row { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.55rem; }

  .bar-row .bar-tag {
    width: 3.4rem;
    flex-shrink: 0;
    font-family: var(--mono);
    font-size: 0.75rem;
    color: var(--color-text-dim);
  }

  .bar-track {
    flex: 1;
    height: 10px;
    background: var(--color-surface-raised);
    border-radius: 999px;
    overflow: hidden;
    border: 1px solid var(--color-border);
  }

  .bar-fill {
    height: 100%;
    border-radius: 999px;
    width: 0%;
    transition: width var(--duration-normal) var(--ease-out-expo);
  }

  .bar-fill.tier-0 { background: var(--color-tier0); }
  .bar-fill.tier-1 { background: var(--color-tier1); }
  .bar-fill.tier-2 { background: var(--color-tier2); }

  .bar-row .bar-count {
    font-family: var(--mono);
    font-size: 0.78rem;
    color: var(--color-text-dim);
    width: 1.6rem;
    text-align: right;
  }

  .demo-banner {
    margin: 0 clamp(1.25rem, 4vw, 3rem);
    padding: 0.6rem 1rem;
    background: rgba(255, 176, 32, 0.1);
    border: 1px solid rgba(255, 176, 32, 0.35);
    color: var(--color-tier1);
    border-radius: 10px;
    font-size: 0.82rem;
    display: none;
  }

  .demo-banner.visible { display: block; }

  footer {
    text-align: center;
    color: var(--color-text-dim);
    font-size: 0.78rem;
    padding: 1.5rem 1rem 2.5rem;
  }

  .spinner {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255,255,255,0.35);
    border-top-color: #fff;
    border-radius: 50%;
    display: inline-block;
    animation: spin 0.7s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<header>
  <div class="brand">
    <span class="brand-mark" aria-hidden="true"></span>
    <h1>Routing Agent</h1>
  </div>
  <p>
    Tiered cascade routing: deterministic solvers first, then the cheapest
    adequate model, escalating only when the confidence gate fails. Every
    prompt below runs the real cascade.
  </p>
</header>

<div class="demo-banner" id="demoBanner">
  Demo mode — no FIREWORKS_API_KEY configured. Tier-0 (zero-token) prompts
  work; model-routed prompts will return a 503.
</div>

<main>
  <section class="panel" aria-labelledby="solve-heading">
    <h2 id="solve-heading">Submit a prompt</h2>
    <textarea
      id="promptInput"
      placeholder="e.g. What is 17% of 340?"
      aria-label="Prompt input"
    ></textarea>
    <div class="row">
      <div class="examples">
        <button class="chip" type="button" data-prompt="What is 17% of 340?">
          arithmetic
        </button>
        <button
          class="chip"
          type="button"
          data-prompt="How many days between 2026-01-01 and 2026-07-04?"
        >
          date math
        </button>
        <button class="chip" type="button" data-prompt="Reverse the string 'fireworks'">
          string op
        </button>
        <button
          class="chip"
          type="button"
          data-prompt="Summarize the plot of a heist movie in one sentence."
        >
          summarization
        </button>
      </div>
      <button class="submit" id="submitBtn" type="button">Route &amp; Solve</button>
    </div>
    <div class="error-box" id="errorBox" role="alert"></div>
    <div class="answer-box" id="answerBox" aria-live="polite"></div>

    <div class="route-grid" id="routeGrid" style="display:none;">
      <div class="route-card">
        <div class="label">Tier</div>
        <div class="value" id="routeTier">&mdash;</div>
      </div>
      <div class="route-card">
        <div class="label">Model</div>
        <div class="value" id="routeModel">&mdash;</div>
      </div>
      <div class="route-card">
        <div class="label">Task type</div>
        <div class="value" id="routeTaskType">&mdash;</div>
      </div>
      <div class="route-card">
        <div class="label">Tokens (total)</div>
        <div class="value" id="routeTokens">&mdash;</div>
      </div>
      <div class="route-card">
        <div class="label">Cost (USD)</div>
        <div class="value" id="routeCost">&mdash;</div>
      </div>
      <div class="route-card">
        <div class="label">Savings vs baseline</div>
        <div class="value" id="routeSavings">&mdash;</div>
      </div>
    </div>
  </section>

  <section class="panel" aria-labelledby="stats-heading">
    <h2 id="stats-heading">Running savings</h2>
    <div class="stat-list">
      <div class="stat-item">
        <span class="stat-label">Prompts solved</span>
        <span class="stat-value" id="statSolved">0</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Total tokens spent</span>
        <span class="stat-value" id="statTokens">0</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Baseline estimate tokens</span>
        <span class="stat-value" id="statBaseline">0</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Cumulative savings</span>
        <span class="stat-value accent" id="statSavings">0%</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Total cost (USD)</span>
        <span class="stat-value good" id="statCost">$0.000000</span>
      </div>
    </div>

    <div class="bar-wrap">
      <h2 style="margin-top:0.25rem;">Model-call tier distribution</h2>
      <div class="bar-row">
        <span class="bar-tag">tier1</span>
        <div class="bar-track"><div class="bar-fill tier-1" id="barTier1"></div></div>
        <span class="bar-count" id="countTier1">0</span>
      </div>
      <div class="bar-row">
        <span class="bar-tag">tier2</span>
        <div class="bar-track"><div class="bar-fill tier-2" id="barTier2"></div></div>
        <span class="bar-count" id="countTier2">0</span>
      </div>
    </div>
  </section>
</main>

<footer>AMD Hackathon ACT II · Track 1 — Hybrid Token-Efficient Routing Agent</footer>

<script>
(function () {
  "use strict";

  const promptInput = document.getElementById("promptInput");
  const submitBtn = document.getElementById("submitBtn");
  const answerBox = document.getElementById("answerBox");
  const errorBox = document.getElementById("errorBox");
  const routeGrid = document.getElementById("routeGrid");
  const demoBanner = document.getElementById("demoBanner");

  document.querySelectorAll(".chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      promptInput.value = chip.getAttribute("data-prompt");
      promptInput.focus();
    });
  });

  function tierBadge(tier) {
    const span = document.createElement("span");
    span.className = "tier-badge tier-" + tier;
    span.textContent = "TIER " + tier;
    return span.outerHTML;
  }

  function setError(message) {
    errorBox.textContent = message;
    errorBox.classList.toggle("visible", Boolean(message));
  }

  async function submitPrompt() {
    const prompt = promptInput.value.trim();
    if (!prompt) {
      setError("Enter a prompt first.");
      return;
    }
    setError("");
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span> Routing…';
    answerBox.classList.remove("visible");

    try {
      const response = await fetch("/solve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt }),
      });
      const data = await response.json();

      if (!response.ok) {
        setError(data.detail || "Request failed.");
        routeGrid.style.display = "none";
        return;
      }

      answerBox.textContent = data.answer || "(empty answer)";
      answerBox.classList.add("visible");

      document.getElementById("routeTier").innerHTML = tierBadge(data.route.tier);
      document.getElementById("routeModel").textContent = data.route.model || "(none — solver)";
      document.getElementById("routeTaskType").textContent = data.route.task_type;
      document.getElementById("routeTokens").textContent = data.tokens.total;
      document.getElementById("routeCost").textContent = "$" + data.cost_usd.toFixed(6);
      document.getElementById("routeSavings").textContent = data.savings_pct + "%";
      routeGrid.style.display = "grid";

      await refreshStats();
    } catch (err) {
      setError("Network error: " + err.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Route & Solve";
    }
  }

  async function refreshStats() {
    try {
      const response = await fetch("/api/stats");
      const data = await response.json();

      demoBanner.classList.toggle("visible", Boolean(data.demo_mode));
      document.getElementById("statSolved").textContent = data.solved_count;
      document.getElementById("statTokens").textContent = data.total_raw_tokens;
      document.getElementById("statBaseline").textContent = data.baseline_estimate_tokens;
      document.getElementById("statSavings").textContent = data.savings_pct + "%";
      document.getElementById("statCost").textContent = "$" + data.total_cost_usd.toFixed(6);

      const dist = data.tier_call_distribution || {};
      const t1 = dist.tier1 || 0;
      const t2 = dist.tier2 || 0;
      const maxCount = Math.max(t1, t2, 1);

      document.getElementById("countTier1").textContent = t1;
      document.getElementById("countTier2").textContent = t2;
      document.getElementById("barTier1").style.width = (100 * t1 / maxCount) + "%";
      document.getElementById("barTier2").style.width = (100 * t2 / maxCount) + "%";
    } catch (err) {
      // Stats refresh is best-effort; a failure here shouldn't block the UI.
      console.warn("stats refresh failed", err);
    }
  }

  submitBtn.addEventListener("click", submitPrompt);
  promptInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      submitPrompt();
    }
  });

  refreshStats();
})();
</script>
</body>
</html>
"""


def main() -> None:
    """Run the demo app with uvicorn, host 0.0.0.0, port from PORT env
    (default 8000). Entry point for `python -m routing_agent.webapp`.
    """
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)  # noqa: S104 (demo binds all interfaces intentionally)


if __name__ == "__main__":
    main()
