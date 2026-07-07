# routing-agent

[![CI](https://github.com/SebAustin/amd-routing-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/SebAustin/amd-routing-agent/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

**AMD Developer Cloud Hackathon — ACT II, Track 1.** A hybrid token-efficient
routing agent: every task is resolved by a deterministic Tier-0 solver first
(zero Fireworks tokens), then by the cheapest model adequate for the task
type, with a single escalation to the strongest allowed model if the answer
fails a confidence gate — no loops, no self-verification, no wasted calls.
The cascade turns "throw the biggest model at everything" into a
precision-first, cost-aware pipeline that still lands 99.5% accuracy.

## Results (evals/reports/tuned-live.json)

Full 200-task evalset, live Fireworks API, policy `tuned`:

| Metric | Value |
|---|---|
| Accuracy | **99.5%** (199/200) |
| Zero-token tasks (Tier 0) | **32.5%** (65/200) |
| Token reduction vs naive baseline | **~47–51%** (short of the 60% stretch target, SC2 — see `evals/README.md` "Tuning notes" for the measured range and why) |
| Total cost (price-weighted) | **$0.003636** for 200 tasks |
| Total raw tokens | 17,157 (12,110 prompt / 5,047 completion) |
| Wall time | 23.2s (200 tasks, 8-way concurrency) |
| Route distribution | tier0: 65 · tier1 gpt-oss-20b: 76 · tier1 gpt-oss-120b: 48 · tier1 deepseek-v4-flash: 10 · tier2 deepseek-v4-pro: 1 |

The one miss (`summarization-003`) is a grading artifact: the model's
paraphrase drops a literal keyword (`declin[e/ing]`) that the `contains_all`
grader requires, not a wrong answer. See `evals/README.md` for the full
tuning ladder and the baseline methodology behind the token-reduction range.

## Architecture

```
task → TaskClassifier (0 tokens: regex/heuristics)
  ├─ Tier 0: deterministic solvers (0 tokens): arithmetic (safe AST eval),
  │          date math, string ops, unit conversion, regex extraction.
  │          Precision-first: solver fires only when it can self-validate;
  │          otherwise falls through.
  ├─ Tier 1: cheapest adequate allowed model (gemma* preferred at equal
  │          tier; today: gpt-oss-20b / gpt-oss-120b / deepseek-v4-flash).
  │          Minimal prompt, per-task-type max_tokens cap, stop sequences,
  │          temperature=0, reasoning suppressed per model profile.
  │          → ConfidenceGate — PRIMARY: output-format validation +
  │             Tier-0 cross-check; SECONDARY: answer-token logprobs
  │             (available live but unwired — see ARCHITECTURE.md).
  │             pass → answer · fail → Tier 2
  └─ Tier 2: single escalation to strongest allowed model, then accept.
             Never loop; no LLM self-verification (costs more tokens than
             it buys).
```

Full module-by-module design, a worked example per tier, and the ADRs
behind these choices: [ARCHITECTURE.md](ARCHITECTURE.md).

### Why this wins on tokens

- **Zero-token Tier-0.** Arithmetic, date math, string ops, unit
  conversion, and regex extraction are solved locally with a safe AST
  evaluator / `python-dateutil` / regex — no API call, no tokens, no
  latency. 32.5% of the evalset never touches Fireworks.
- **Reasoning suppression per model.** `gpt-oss-20b`/`120b` are reasoning
  models that burn completion tokens on hidden `reasoning_content`; the
  registry carries a `reasoning_profile` per model (`reasoning_effort:
  "low"` for gpt-oss, `"none"` for the Tier-2 escalation model) plus a
  `min_viable_max_tokens` floor tuned against live truncation failures
  (`src/routing_agent/registry.py`).
- **Minimal prompts + caps + stop sequences.** `prompts.py` sends
  answer-only system contracts (≤12 words, or no system message at all)
  with a per-task-type `max_tokens` cap and a `"\n"` stop sequence for
  single-line answer types — no chain-of-thought, no boilerplate.
  Retries (empty-content trap) are counted in the ledger and capped, so
  the cascade can't quietly erase its own savings.
- **Single-escalation policy.** At most 2 model calls per task, ever. No
  self-verification loop — verifying with another LLM call costs more
  tokens than the accuracy it would buy.
- **Prompt-overhead-aware model choice.** `registry.cheapest()` ranks
  candidates by blended per-token price, not raw parameter count, so the
  router doesn't pick a model whose chat-template overhead outweighs its
  price advantage on short tasks.

### Gemma-aware routing (partner prize)

`registry.cheapest()` prefers a `gemma*`-family model at equal price tier
over any other family — this is a plain sort-key tiebreak
(`0 if m.is_gemma else 1`), unit-tested in `tests/test_registry.py`. As of
the July 7 live probe (`PLAN.md` §2), Fireworks' serverless catalog on this
account returns `NOT_FOUND` for every Gemma variant, so Gemma never wins a
route today — but the registry ships full metadata for 7 Gemma variants
(`gemma-3-1b-it` through `gemma-4-31b-it`, `serverless=False`) and the
preference activates automatically the moment `ALLOWED_MODELS` exposes one,
with no code change.

## Quickstart

```bash
# Install deps (uv-managed venv, dev group included)
uv sync --group dev

# Configure credentials
cp .env.example .env
# edit .env: FIREWORKS_API_KEY, ALLOWED_MODELS

# Run the test suite (fully offline — HTTP mocked with respx)
uv run pytest -q

# Lint / format check
uv run ruff check .
uv run ruff format --check .
```

### Run the adapter on a sample tasks.json

```bash
cat > /tmp/tasks.json <<'EOF'
[
  {"id": "1", "prompt": "What is 17% of 340?"},
  {"id": "2", "prompt": "Summarize the plot of a heist movie in one sentence."}
]
EOF

# The adapter reads FIREWORKS_API_KEY / ALLOWED_MODELS from the environment:
set -a && source .env && set +a

uv run python -m routing_agent.adapter --input /tmp/tasks.json --output /tmp/results.json
cat /tmp/results.json
```

Task 1 resolves at Tier 0 (arithmetic solver, 0 tokens); task 2 needs a
model call (Tier 1). The run summary (route distribution, token totals) is
logged to **stderr**, never mixed into `results.json`.

### Run the demo webapp

```bash
uv run python -m routing_agent.webapp
# open http://localhost:8000
```

If `FIREWORKS_API_KEY` is unset, the app boots anyway in Tier-0-only demo
mode (model-routed prompts return `503` instead of crashing).

### Run the evals

```bash
# Free: Tier-0/classifier coverage only, no network
uv run python evals/run_eval.py --policy tuned --dry-run

# Full cascade against the live Fireworks API (writes evals/reports/tuned-live.json)
uv run python evals/run_eval.py --policy tuned

# Filter / limit
uv run python evals/run_eval.py --policy tuned --categories arithmetic,dates
uv run python evals/run_eval.py --policy tuned --limit 20

# Naive baseline for the SC2 comparison (strongest model, generic prompt,
# max_tokens=512, reasoning suppression explicitly bypassed)
uv run python evals/run_eval.py --baseline --limit 60 --stratified --policy tuned
```

See [evals/README.md](evals/README.md) for the evalset breakdown, graders,
and the full tuning ladder.

## Docker / harness contract

The containerized harness mode is **the submission entrypoint**. The
scoring pipeline builds `Dockerfile` (repo root) and runs it against
`/input/tasks.json` → `/output/results.json`:

```bash
docker build -t routing-agent:latest .

docker run --rm \
  -v "$(pwd)/input:/input:ro" \
  -v "$(pwd)/output:/output" \
  -e FIREWORKS_API_KEY="$FIREWORKS_API_KEY" \
  -e FIREWORKS_BASE_URL="https://api.fireworks.ai/inference/v1" \
  -e ALLOWED_MODELS="accounts/fireworks/models/gpt-oss-20b,accounts/fireworks/models/deepseek-v4-flash,accounts/fireworks/models/glm-5p1" \
  routing-agent:latest
```

- Route/token/cost summary goes to stderr only; `results.json` contains
  only `{id, output}` pairs.
- `MAX_INPUT_BYTES` (50 MB) and `MAX_TASKS` (10,000) guard against a
  hostile/malformed input file.
- `docker-compose.yml` wraps the same command for local dry runs
  (`docker compose run --rm harness`) and exposes a `demo` service that
  runs the webapp on `:8000` instead.

Full deployment reference (two Dockerfiles, HF Space assembly, rollback):
[DEPLOYMENT.md](DEPLOYMENT.md).

## Configuration reference

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `FIREWORKS_API_KEY` | *(required)* | Missing key → harness mode (`adapter.py`) fails fast at startup (exit 1); demo webapp instead boots in Tier-0-only mode. |
| `FIREWORKS_BASE_URL` | `https://api.fireworks.ai/inference/v1` | OpenAI-compatible endpoint; override for a proxy (e.g. a Gemma-exposing proxy). |
| `ALLOWED_MODELS` | *(empty)* | Comma-separated, JSON array, or bare/prefixed model names — see `config.py:parse_allowed_models`. |
| `ROUTING_POLICY_PATH` | built-in `Policy()` defaults | Path to a routing policy YAML (`evals/policies/default.yaml` or `tuned.yaml`). |
| `PORT` | `8000` | Demo webapp bind port only; the harness image (adapter) has no HTTP server. |
| `RATE_LIMIT_PER_MIN` | `10` | Demo webapp: per-client sliding-window cap on `POST /solve`. |
| `DEMO_DAILY_BUDGET_USD` | `1.00` | Demo webapp: global daily price-weighted spend cap; Tier-0 keeps working after it's hit. |

### Policy YAML knobs (`evals/policies/*.yaml`)

| Key | Meaning |
|---|---|
| `confidence_threshold` | Reserved threshold knob (0.0–1.0); current gate is format+cross-check based, see ARCHITECTURE.md. |
| `logprob_threshold` | Reserved for the (currently unwired) logprob secondary signal. |
| `retry_budget` | Max empty-content retries per call (client floors/multiplies `max_tokens` on retry). |
| `objective` | `raw_tokens` (default, scoring assumption) or `price_weighted`. |
| `max_tokens` | Per-task-type completion cap, e.g. `classification: 8`, `code: 256`. Falls back to `general` if a type is missing. |

## Repo map

| Path | What it is |
|---|---|
| `src/routing_agent/` | Package: config, models, registry, client, classifier, prompts, router, adapter, webapp, `solvers/`. |
| `evals/` | 200-task evalset (`evalset/*.jsonl`), graders, `run_eval.py`, policies, committed reports (`reports/*.json`). |
| `tests/` | Unit tests, fully offline (HTTP mocked with `respx`). |
| `Dockerfile` | Harness/scoring image — `ENTRYPOINT` runs the adapter. |
| `Dockerfile.spaces` | Hugging Face Space image variant — runs the webapp on port 7860. |
| `docker-compose.yml` | Local `harness` and `demo` services. |
| `spaces/README.md` | HF Space card + assembly instructions (packaging only). |
| `.github/workflows/ci.yml` | Ruff format/lint + pytest + Docker build, fully mocked (no secrets). |
| `PLAN.md` | Design doc: goals, success criteria, architecture, milestones. |
| `ASSUMPTIONS.md` | Logged assumptions about the unknown harness contract, with mitigations. |
| `SECURITY.md` | STRIDE threat model, secret-scan results, findings table. |
| `DEPLOYMENT.md` | Where things run, env var reference, rollback, operational notes. |
| `ARCHITECTURE.md` | Module walkthrough, routing flow, ADRs. |
| `RUNBOOK.md` | Operate/monitor/troubleshoot reference. |
