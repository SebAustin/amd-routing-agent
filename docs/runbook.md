# RUNBOOK

Operate, monitor, and troubleshoot the routing agent. For design rationale
see [ARCHITECTURE.md](../ARCHITECTURE.md); for the threat model see
[SECURITY.md](../SECURITY.md); for deploy topology see
[DEPLOYMENT.md](../DEPLOYMENT.md).

## 1. Environment setup

```bash
uv sync --group dev
cp .env.example .env
# edit .env: FIREWORKS_API_KEY (required for any Tier-1/Tier-2 call),
# ALLOWED_MODELS (comma-separated Fireworks model ids)
```

`uv sync --group dev` installs the `dev` dependency group (pytest, ruff,
respx) on top of the runtime deps (openai, pydantic, fastapi, uvicorn,
python-dateutil, pyyaml, httpx). The harness/Space Docker images run
`uv sync --frozen --no-dev` instead — no test tooling ships in production
images.

## 2. Running each mode

### Harness mode (adapter) — the submission entrypoint

```bash
# Local, no Docker:
uv run python -m routing_agent.adapter --input /path/to/tasks.json --output /path/to/results.json

# Or via /input,/output default paths + stdin fallback:
uv run python -m routing_agent            # delegates to adapter.main()

# Containerized (matches the harness contract exactly):
docker build -t routing-agent:latest .
docker run --rm \
  -v "$(pwd)/input:/input:ro" \
  -v "$(pwd)/output:/output" \
  -e FIREWORKS_API_KEY="$FIREWORKS_API_KEY" \
  -e ALLOWED_MODELS="accounts/fireworks/models/gpt-oss-20b,accounts/fireworks/models/deepseek-v4-flash,accounts/fireworks/models/glm-5p1" \
  routing-agent:latest
```

Exit code `0` on success, `1` on startup failure (bad input JSON, missing
`FIREWORKS_API_KEY`). `results.json` contains only `[{"id", "output"}, ...]`
— routing/token metadata never touches this file.

### Demo webapp

```bash
uv run python -m routing_agent.webapp
# http://localhost:8000  (dashboard: POST /solve, GET /api/stats, GET /healthz)

# Containerized (Space variant, port 7860):
docker build -f Dockerfile.spaces -t routing-agent-demo:latest .
docker run --rm -p 7860:7860 -e FIREWORKS_API_KEY="$FIREWORKS_API_KEY" routing-agent-demo:latest

# Or via compose (harness image, port 8000, command override):
docker compose up demo
```

If `FIREWORKS_API_KEY` is unset, the app boots in Tier-0-only demo mode
(logged as a `WARNING`) — Tier-0 prompts (arithmetic/dates/strings/units/
extraction) keep working; anything needing a model call returns `503`.

### Eval mode

```bash
# Free — Tier-0/classifier coverage only, no network, no cost
uv run python evals/run_eval.py --policy tuned --dry-run

# Full cascade against the live Fireworks API
uv run python evals/run_eval.py --policy tuned

# Filtered / limited
uv run python evals/run_eval.py --policy tuned --categories arithmetic,dates
uv run python evals/run_eval.py --policy tuned --limit 20

# Naive-baseline comparison run (SC2 bar; stratified sample keeps live cost small)
uv run python evals/run_eval.py --baseline --limit 60 --stratified --policy tuned
```

Writes `evals/reports/<policy>-<mode>.json`. Concurrency defaults to 8
workers (`--concurrency N` to override); individual task failures in eval
mode are caught and recorded as a wrong answer + error string rather than
crashing the whole run (`evals/run_eval.py`, `except Exception` around each
task future) — **this per-task isolation exists only in the eval runner,
not in `adapter.py`** (see §5, "empty content / errors").

### Tests and lint

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

CI (`.github/workflows/ci.yml`) runs the same three commands plus a
Docker build (no push), fully offline — no secrets, all Fireworks calls
mocked with `respx`.

## 3. Reading the run summary on stderr

`adapter.py::main()` logs one line to stderr at the end of every run:

```
INFO:routing_agent.adapter:run summary: {"total_tasks": 200, "tier_distribution": {"0": 65, "1": 134, "2": 1}, "task_type_distribution": {...}, "total_raw_tokens": 17157, "total_price_weighted_usd": 0.003636, "total_calls": 138, "retried_calls": 2}
```

| Field | Meaning |
|---|---|
| `total_tasks` | Tasks read from input. |
| `tier_distribution` | Count of tasks resolved at each tier (`0`/`1`/`2`). |
| `task_type_distribution` | Count per classified `TaskType`. |
| `total_raw_tokens` | Sum of prompt+completion tokens across all calls, including retries. |
| `total_price_weighted_usd` | Same calls priced via registry `price_in`/`price_out`. |
| `total_calls` | Number of Fireworks API calls made (not tasks — a Tier-2 escalation is 2 calls for 1 task). |
| `retried_calls` | Calls that hit the empty-content retry path. |

`webapp.py` and `adapter.py` both route logging through the stdlib
`logging` module at `INFO` level to stderr; `results.json`/HTTP responses
never carry this data (`SECURITY.md` — repudiation/info-disclosure rows).

## 4. Interpreting `evals/reports/*.json` fields

Top-level (see `evals/reports/tuned-live.json` for a worked example):

| Field | Meaning |
|---|---|
| `mode` | `"live"`, `"dry_run"`, or `"baseline"`. |
| `total_tasks`, `correct`, `accuracy` | Overall grading result. |
| `by_category` | Per-category `{total, correct, accuracy}` — check here first if accuracy drops; a single category regressing usually means a classifier or prompt-contract regression for that type. |
| `route_distribution` | Count of tasks per `"tier0"` / `"tier1:<model-id>"` / `"tier2:<model-id>"` route string. |
| `zero_token_tasks`, `zero_token_rate` | SC3 metric (≥30% target). |
| `error_count`, `errors` | Tasks that raised during solving (network error, malformed response) — graded as wrong, not silently dropped. |
| `results[]` | Per-task: `id`, `category`, `task_type`, `route`, `retried`, `escalated`, `correct`, `error`, `calls_made` (cumulative call counter across the run, not per-task — don't read it as "calls for this task"). |
| `total_raw_tokens`, `total_prompt_tokens`, `total_completion_tokens` | Ledger totals for the whole run. |
| `total_price_weighted_usd` | Price-weighted total. |
| `total_calls`, `retried_calls`, `retry_rate` | Call-level stats. |
| `elapsed_s` | Wall-clock time for the whole eval run (concurrent workers). |

If `error_count > 0`, check `errors[]` for the task id and exception
string first — this is almost always a transient Fireworks issue (429/5xx)
that reran fine on a second pass, or a genuinely unsupported prompt shape.

## 5. Common failures

| Symptom | Cause | Behavior / fix |
|---|---|---|
| Adapter exits `1` immediately, stderr: `FIREWORKS_API_KEY is required and was not set` | Missing/empty `FIREWORKS_API_KEY` env var | `Settings.from_env()` fails fast at startup (`config.py`) — this is intentional so a misconfigured harness run fails immediately instead of producing an empty/garbage `results.json`. Set the env var and rerun. |
| Adapter exits `1`, stderr mentions `top-level JSON array` or `no task input provided` | Malformed/empty `tasks.json`, or oversized input (`MAX_INPUT_BYTES`=50MB) / too many tasks (`MAX_TASKS`=10,000) | Fix the input file. These are `ValueError`s raised in `_read_tasks`/`_parse_tasks`, caught in `main()`, logged, and turned into exit code 1 — no partial `results.json` is written. |
| Model id returns `NOT_FOUND` (e.g. any `gemma*` id today, per `PLAN.md` §2 live probe) | Model isn't serverless-callable on the account despite being in `ALLOWED_MODELS`/registry | **No automatic fallback exists in the router today** — `registry.resolve_allowed()` trusts `ALLOWED_MODELS` and will select a `NOT_FOUND` model if it's cheapest/strongest for the capability; the resulting `openai` SDK exception propagates uncaught out of `client.complete()`. In harness mode (`adapter.py`) this crashes the whole run (no per-task isolation there — only `evals/run_eval.py` isolates task-level errors). **Mitigation:** only include ids you've confirmed are live-callable in `ALLOWED_MODELS` (probe with a cheap request first, or use the known-good default set: `gpt-oss-20b`, `gpt-oss-120b`, `deepseek-v4-flash`, `deepseek-v4-pro`, `glm-5p1`). |
| Fireworks returns `429` or `5xx` | Rate limit or upstream outage | `client.py` has **no retry/backoff for HTTP-level errors** (only the empty-content retry-once is implemented). The `openai` SDK's exception propagates uncaught: crashes `adapter.py` (no per-task try/except in `run()`), but is caught and recorded per-task in `evals/run_eval.py`. If this matters for the harness run, wrap the harness invocation with your own retry/backoff at the process level, or file this as a follow-up in `adapter.py` (the one file that's safe to extend without touching routing logic). |
| Model returns empty `content` | Reasoning-token trap — e.g. `gpt-oss-20b` spends its whole `max_tokens` budget on hidden `reasoning_content` before any visible answer | `client.complete()` retries once automatically with `max_tokens × 3` (`_RETRY_MAX_TOKENS_MULTIPLIER = 3`), logged at `INFO`: `"empty content on first attempt, retrying with larger cap"`. The retry call is recorded in the ledger (`retry=True`) and counts toward `total_raw_tokens`. If it's still empty after the retry, the Tier-1 answer will fail `_validate_format` (empty string) and escalate to Tier 2. |
| Eval run shows unexpectedly low accuracy in one category only | Classifier misroute or a prompt-contract regression for that `task_type` | Check `by_category` in the report first, then `results[]` filtered to that category for `route`/`error` fields. Cross-reference `tests/test_classifier.py`'s regression table and the tuning notes in `evals/policies/tuned.yaml`'s header comment — 8 regex bugs and 4 solver precision bugs were fixed there; a new evalset addition can surface a similar gap. |
| `summarization-003` (or similar `contains_all`-graded task) marked wrong despite a correct-looking answer | Grading artifact: the model's paraphrase drops a literal required keyword | Known, accepted residual (`evals/README.md` "Tuning notes" #3) — not a routing bug. Diminishing returns to chase further on a 5-task category. |

## 6. Rate limit / budget cap behavior (demo webapp only)

- **Rate limit** (`RATE_LIMIT_PER_MIN`, default 10/min per client IP,
  `webapp.py::SlidingWindowRateLimiter`): exceeding it returns `429` with
  `{"detail": "rate limit exceeded: max N requests per minute..."}`.
  Sliding window, not fixed-bucket — a burst can't straddle two windows to
  double the effective limit. In-memory, single-process only.
- **Daily budget cap** (`DEMO_DAILY_BUDGET_USD`, default `$1.00`,
  `webapp.py::DailyBudgetTracker`): tracked from the same price-weighted
  `TokenLedger` `/api/stats` reads. Once the UTC-day total reaches the cap,
  any `/solve` request that would need a paid model call returns `503`
  (`"demo budget reached for today"`). **Tier-0 requests always keep
  working**, even past the cap, since they cost nothing — the demo stays
  visibly "alive" instead of going fully dark. Resets automatically on UTC
  day rollover; no restart needed.
- Neither guard is shared across processes/replicas — correct for the
  single-instance HF Space deployment this ships as, not a substitute for
  real auth/quota infra if the demo scales out.

## 7. API key rotation procedure

1. Generate a new key in the Fireworks console.
2. Update the **harness/scoring** key wherever the harness operator stores
   secrets (out of this repo's control — communicate the new value through
   the harness's secret channel).
3. Update the **local** `.env` (gitignored, never committed) with the new
   value.
4. Update the **HF Space** secret:
   ```bash
   hf repo secrets set FIREWORKS_API_KEY --repo-type space SebAustin/amd-routing-agent-demo
   # prompts interactively — never pass the value as a CLI literal or echo it
   ```
5. Revoke the old key in the Fireworks console once both are confirmed
   working.
6. Per `SECURITY.md`'s public-release checklist: the development key was
   shared in a chat channel during the hackathon — rotate it after the
   hackathon regardless of whether the secret scan found it in git history
   (it didn't; this is cheap insurance, not incident response).

## 8. When the real harness spec lands

Per `ASSUMPTIONS.md` #1–#3 and ADR-2 (`docs/adr/0002-...`), the harness
I/O contract was unpublished at build time and isolated entirely to one
file:

1. Edit **`src/routing_agent/adapter.py`** only — update `_read_tasks`,
   `_parse_tasks`, and/or the `results.json` write shape to match the
   published contract. If the field-name aliasing differs, also check
   `_PROMPT_ALIASES` in `src/routing_agent/models.py`.
2. Re-run the full check sequence:
   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run pytest -q
   uv run python evals/run_eval.py --policy tuned --dry-run   # sanity, no cost
   uv run python evals/run_eval.py --policy tuned             # full re-verify
   ```
3. Confirm `docker build -t routing-agent:latest .` still succeeds and
   `docker run` against a sample of the *real* published `tasks.json`
   produces a valid `results.json`.
4. Done — router, classifier, solvers, registry, prompts, and their test
   suites do not change.
