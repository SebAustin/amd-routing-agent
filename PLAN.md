# PLAN — Hybrid Token-Efficient Routing Agent (AMD Hackathon ACT II, Track 1)

## 1. Goal & success criteria

Build an AI agent that completes a fixed set of tasks autonomously, minimizing **Fireworks AI tokens** while staying above the accuracy threshold. Leaderboard: token count + output accuracy. Deadline **July 11, 2026**.

Measurable success criteria:
- **SC1**: Local eval accuracy ≥ 90% on the project eval set (assumed threshold until the official one is published).
- **SC2**: ≥ 60% reduction in total Fireworks tokens vs the baseline policy (all tasks → strongest model, default prompts). *Stretch target — re-baselined after eval v1 measures the real Tier-0 hit rate; retry tokens count toward the total.*
- **SC3**: ≥ 30% of eval tasks resolved with **zero** Fireworks tokens (Tier 0).
- **SC4**: `docker run` with mounted `/input/tasks.json` produces a valid `/output/results.json` (assumed harness contract; isolated in `adapter.py`).
- **SC5**: Public repo + README + demo URL + CI green; no secrets in code or git history.
- **SC6**: Gemma-preference routing demonstrably activates when a `gemma*` model appears in `ALLOWED_MODELS` (unit-tested), for the Gemma partner prize.

Non-goals: fine-tuning (not needed to win on routing); local GPU inference in the scored path (unscored anyway); multi-turn agent frameworks (adds token overhead).

## 2. Live environment facts (probed July 7 with the real key)

- Key works against `https://api.fireworks.ai/inference/v1` (OpenAI-compatible; `usage` in every response; `prompt_tokens_details.cached_tokens` present).
- `GET /models` lists only: `gpt-oss-120b`, `glm-5p1`, `glm-5p2`, `deepseek-v4-pro`, `kimi-k2p5`, `kimi-k2p6` (+ an image model). **Unlisted models can still be callable**: `gpt-oss-20b` and `deepseek-v4-flash` respond fine → trust `ALLOWED_MODELS`, probe at startup, never assume the listing is complete.
- **All Gemma variants return NOT_FOUND** on this account today. Gemma prize path = hackathon proxy exposing Gemma via `FIREWORKS_BASE_URL`, or self-hosted on AMD Developer Cloud. Registry keeps `gemma*` preference; activates automatically if allowed.
- **Reasoning-token trap**: `gpt-oss-20b` burns completion tokens on `reasoning_content` (with `max_tokens=10` it returned *no* content); its chat template costs ~82 prompt tokens for a 10-word message. `deepseek-v4-flash` has ~14-token overhead but inlines thinking into `content` when truncated. → Per-model **overhead + reasoning-suppression profiles** (e.g. `reasoning_effort: "low"`, thinking toggles, retry-once-with-larger-cap on empty content) are first-class registry metadata, tuned by the eval harness.

## 3. Architecture — tiered routing cascade

```
task → TaskClassifier (0 tokens: regex/heuristics; optional local embeddings — local inference unscored ⇒ free)
  ├─ Tier 0: deterministic solvers (0 tokens): arithmetic (safe AST eval), date math, string ops,
  │          unit conversion, regex extraction, JSON parsing. Precision-first: solver fires only
  │          when it can self-validate; otherwise falls through.
  ├─ Tier 1: cheapest adequate allowed model (gemma* preferred at equal tier; today: gpt-oss-20b /
  │          deepseek-v4-flash). Minimal prompt, per-task-type max_tokens cap, stop sequences,
  │          temperature=0, reasoning suppressed per model profile.
  │          → ConfidenceGate — PRIMARY: output-format validation + Tier-0 cross-checks;
  │             SECONDARY: answer-token logprobs (probed live: returned by all candidates, but the
  │             stream includes reasoning-channel tokens, so only the trailing answer tokens count).
  │             pass → answer · fail → Tier 2
  └─ Tier 2: single escalation to strongest allowed model, then accept. Never loop; no LLM
             self-verification (costs more tokens than it buys).
```

Components:
- `config.py` — env parsing (`FIREWORKS_API_KEY`, `FIREWORKS_BASE_URL`, `ALLOWED_MODELS`), YAML policy loading.
- `adapter.py` — **the only harness-facing module**: `/input/tasks.json` → `/output/results.json`, plus CLI/stdin modes. When the real spec lands, only this file changes.
- `classifier.py` — zero-token task typing (ordered regex/heuristic rules; category → solver/prompt template).
- `solvers/` — Tier-0: `arithmetic.py`, `dates.py`, `strings.py`, `units.py`, `extraction.py`. Each returns `(answer, confident: bool)`.
- `registry.py` — model metadata: id, price in/out, size tier, capability tags, quality rank, **prompt-overhead estimate, reasoning profile (params to suppress thinking), min viable max_tokens**. Intersects with `ALLOWED_MODELS`; name-heuristic tiering for unknown ids; `cheapest_allowed(capability)` with `gemma*` preference at equal tier.
- `client.py` — `openai` SDK against `FIREWORKS_BASE_URL`; wrapper records every call (model, usage, latency, route path) in a `TokenLedger` (raw tokens **and** price-weighted — scoring metric ambiguity hedge); retry-once-with-larger-cap on empty content — **retry tokens are counted in the ledger and capped by a per-task-type retry budget so retries can't erase the savings they protect**.
- `router.py` — cascade orchestration, confidence gate (logprob thresholds from policy YAML), single-escalation policy.
- `prompts.py` — minimal per-task-type templates (≤10-token system text or none; answer-only contracts; per-type max_tokens/stop).
- `webapp.py` — FastAPI demo: `POST /solve`, dashboard with route decisions, tokens, savings vs baseline.
- `evals/` — 150–300 tasks across arithmetic, dates/strings, classification, extraction, short QA, small code, summarization; graders (exact / normalized / numeric-tolerance); `run_eval.py` emits accuracy, total tokens, route distribution per policy; baseline policy for the headline savings number.

## 4. Repo layout

As approved: `pyproject.toml` (uv; deps: openai, pydantic, fastapi, uvicorn, python-dateutil, pyyaml; dev: pytest, ruff, respx), `src/routing_agent/` package, `evals/`, `tests/`, `Dockerfile` (python:3.12-slim, <500 MB, ENTRYPOINT = adapter, `serve` override), `docker-compose.yml`, `.github/workflows/ci.yml` (ruff + pytest, all API calls mocked), `.env` gitignored with `.env.example` placeholders.

## 5. Milestones (4 days)

| Day | Deliverable |
|---|---|
| 1 (Jul 7) | Intake ✔ (this doc), scaffold, client+registry+config, adapter with assumed contract |
| 1–2 | Tier-0 solvers + classifier + tests; eval set v1 |
| 2–3 | Router + confidence gate + prompts; eval loop; threshold tuning on accuracy/token frontier; live smoke tests |
| 3 | Docker, CI, demo webapp, HF Spaces deploy prep (gated); security audit; **docs + launch-material drafts pulled forward to Day 3** |
| 4 (Jul 10) | **Reserved: real harness integration (adapter only) + eval re-run + submission only** — docs/launch are already drafted |

## 6. Risks & mitigations

1. **Unknown harness interface** (schema, ALLOWED_MODELS format, threshold, scoring metric) — highest risk. → adapter isolation; pydantic `Task`/`Result` stay stable; TokenLedger tracks both raw and price-weighted; watch Discord/participant guide daily; Day-4 integration buffer.
2. **Gemma unavailable serverless** (confirmed today) → registry preference auto-activates if the harness exposes it; SC6 unit-tested regardless; README/demo narrate Gemma-aware routing for the partner prize.
3. **Reasoning models waste tokens / return empty content on tight caps** (confirmed today) → per-model reasoning profiles + retry-once policy + eval-tuned caps.
4. **Tier-0 false positives tank accuracy** → precision-first guards, eval regression gate in CI.
4b. **Eval-set mix is self-authored** and may not match the real task distribution (e.g. summarization-heavy would slash Tier-0 hit rate) → route-distribution results re-validated against any sample tasks the harness publishes; SC2/SC3 re-baselined then.
5. **Time** → demo/video get fixed Day-4 budget; cut few-shot tuning before cutting adapter integration.

## 7. Revision log

- r1 (Jul 7): Initial plan adopted from approved plan-mode design + live API probe findings.
- r2 (Jul 7): plan-critic PASS 90/100 (iteration 1). Folded advisories: SC2 marked stretch + retry accounting; ConfidenceGate primary/secondary split after live logprobs probe (available on all candidates, streams include reasoning tokens); eval-mix risk 4b added; Day 4 reserved for integration+submission only.
