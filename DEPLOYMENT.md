# DEPLOYMENT

Deployment-readiness reference for the Hybrid Token-Efficient Routing Agent
(AMD Hackathon ACT II, Track 1). Pairs with `SECURITY.md` (threat model /
audit) and `PLAN.md` (architecture). This file covers *where things run*,
*how they're wired*, and *what to do if something breaks*.

---

## 1. What deploys where

| Artifact | Where | Status |
|---|---|---|
| Source of truth | GitHub — `github.com/SebAustin/amd-routing-agent`, branch `main` | Live, CI green |
| Scoring harness image | Built from repo-root `Dockerfile`, run by the AMD/Fireworks scoring pipeline | Built on demand by the harness operator, not hosted by this repo |
| Public demo | Hugging Face Space `SebAustin/amd-routing-agent-demo`, `sdk: docker` | **LIVE** — https://sebaustin-amd-routing-agent-demo.hf.space (deployed 2026-07-07 via `scripts/deploy_space.sh`; verified: /healthz ok, Tier-0 solve 0 tokens, model-path solve via gpt-oss-20b). Key stored as a private Space secret; rate limit 10 req/min, $1/day budget cap. |

Two separate Docker images are built from this one repo, from two separate
Dockerfiles, for two separate audiences:

- **`Dockerfile`** (repo root) — the harness/scoring image. `ENTRYPOINT`
  runs `python -m routing_agent.adapter`, which reads `/input/tasks.json`
  and writes `/output/results.json`. This is what the scoring pipeline
  builds and runs; it is the default and does not change for the Space.
- **`Dockerfile.spaces`** (repo root) — the Space/demo image. Same base
  image, same dependency-install steps, same non-root user — the only
  difference is it ends in `ENV PORT=7860`, `EXPOSE 7860`, and
  `CMD ["python", "-m", "routing_agent.webapp"]` to serve the judge-facing
  dashboard on the port Hugging Face Docker Spaces expects. See the header
  comment in that file and `spaces/README.md` for the exact Space-repo
  assembly steps (this repo does not push to the Space itself).

---

## 2. How the scoring harness consumes the image

The harness builds `Dockerfile` (repo root) and runs it with the
input/output contract documented in `PLAN.md` §3/§4:

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

- Reads `input/tasks.json` from the read-only `/input` mount.
- Writes `output/results.json` (`{id, output}` pairs) to the writable
  `/output` mount.
- Route/token/cost summary goes to **stderr**, never into
  `results.json` (`adapter.py` keeps those streams separate by design).
- `MAX_INPUT_BYTES` (50 MB) and `MAX_TASKS` (10,000) guard against a
  hostile/malformed input file (`SECURITY.md` M-1, resolved).
- `docker-compose.yml`'s `harness` service wraps the same command with an
  `.env` file for local dry runs.

Local dry run without a docker build:

```bash
uv run python -m routing_agent.adapter --input evals/evalset/arithmetic.jsonl --output /tmp/results.json
```

---

## 3. Environment variable reference

| Variable | Default | Used by | Notes |
|---|---|---|---|
| `FIREWORKS_API_KEY` | *(required for model calls)* | `adapter.py`, `webapp.py` | Never committed; sourced from `.env` locally (gitignored) or the platform's secret store in any hosted deployment. Missing key → harness mode raises at startup (fail fast); demo webapp instead boots in **Tier-0-only demo mode**. |
| `FIREWORKS_BASE_URL` | `https://api.fireworks.ai/inference/v1` | `adapter.py`, `webapp.py` | OpenAI-compatible endpoint; override for a proxy (e.g. a Gemma-exposing proxy per `PLAN.md` §2). |
| `ALLOWED_MODELS` | *(empty)* | `adapter.py`, `webapp.py` | Comma-separated list, JSON array, or bare/prefixed model names — see `config.py:parse_allowed_models`. Drives which models the router/cheapest/strongest selection can pick from. |
| `ROUTING_POLICY_PATH` | built-in `Policy()` defaults | `adapter.py`, `webapp.py` | Path to a routing policy YAML (`evals/policies/default.yaml` or `tuned.yaml`). |
| `PORT` | `8000` | `webapp.py` (`main()`) | Demo webapp bind port. **The Space image (`Dockerfile.spaces`) hardcodes `ENV PORT=7860`** to match the Hugging Face Docker Space contract; the harness image never uses this var (adapter.py has no HTTP server). |
| `RATE_LIMIT_PER_MIN` | `10` | `webapp.py` (`AppState`) | Per-client sliding-window cap on `POST /solve`, keyed by the first `X-Forwarded-For` address (falls back to the direct peer). Exceeding it returns `429` with a JSON `{"detail": "..."}` body. In-memory, single-process (SECURITY.md M-2). |
| `DEMO_DAILY_BUDGET_USD` | `1.00` | `webapp.py` (`AppState`) | Global daily price-weighted spend cap (UTC calendar day), computed from the same `TokenLedger` the `/api/stats` endpoint reads. Once reached, model-path `/solve` requests return `503` ("demo budget reached for today"); Tier-0 (zero-token) requests keep working regardless. Resets automatically on UTC day rollover — no restart needed. |

All of the above are read at process start (`AppState.__init__` /
`Settings.from_env`) except the rate limiter and budget tracker, which are
re-evaluated on every `/solve` call by design.

---

## 4. Rollback

- **GitHub (source of truth):** revert with a normal `git revert <sha>` (or
  `git reset --hard <known-good-sha>` + force-push only if explicitly
  authorized) and let CI re-verify green before anything downstream is
  rebuilt.
- **Hugging Face Space:** Spaces keep every deployed commit; use the
  Space's **"Revert"** action in the HF UI (Files & versions → pick a prior
  commit → Revert), or push the previous known-good commit SHA from the
  assembled Space repo. Because the Space repo is *assembled* from this
  repo (not a mirror — see `spaces/README.md`), the safe rollback path is
  always: fix/revert in GitHub first, then re-run the assembly + Space push
  from the corrected `main`, rather than hand-editing the Space repo directly.
- **Scoring harness image:** rebuild `Dockerfile` from the desired GitHub
  SHA; no separate rollback mechanism needed since the harness operator
  builds on demand.

---

## 5. The one gated production-deploy step

Everything above this line is safe to run locally/in CI. The following is
the **only** step that touches the live public Space, and it is
**explicitly gated** — this repo/PR does not run it. The operator (or the
orchestrator handling Space secrets, per this task's scope restriction)
runs it manually:

```bash
# 1. Assemble the Space repo from this repo's main branch (see
#    spaces/README.md "How the orchestrator assembles this Space repo"
#    for the exact file mapping: Dockerfile.spaces -> Dockerfile,
#    spaces/README.md -> README.md, src/, evals/policies/, pyproject.toml,
#    uv.lock, README.md).

# 2. Set the Space secret (placeholder only — do not paste a real key
#    into a shell history or a committed file):
hf repo secrets set FIREWORKS_API_KEY --repo-type space SebAustin/amd-routing-agent-demo
#    (prompts for the secret value interactively; never pass it as a CLI
#    literal, never echo it, never commit it)

# 3. Push the assembled Space repo to trigger the HF Docker build + deploy:
git push hf-space main
```

Before running step 2/3, confirm:

- [ ] `uv run ruff format` + `uv run ruff check .` clean, `uv run pytest -q`
      all green on the `main` commit being deployed (see gate output below).
- [ ] `RATE_LIMIT_PER_MIN` and `DEMO_DAILY_BUDGET_USD` are set to
      demo-appropriate values in the Space's env/secrets (defaults of
      `10`/min and `$1.00`/day are conservative starting points, not a
      requirement to change).
- [ ] The key being set in step 2 is a **separate, low-quota key**, not the
      leaderboard/scoring key, per `SECURITY.md`'s public-release checklist.

---

## 6. Operational notes

- **Rate limiting** (`RATE_LIMIT_PER_MIN`, default 10 req/min/client) and
  the **daily spend cap** (`DEMO_DAILY_BUDGET_USD`, default $1.00/day) are
  both in-memory, single-process guards implemented in `webapp.py`
  (`SlidingWindowRateLimiter`, `DailyBudgetTracker`) — see `SECURITY.md`
  M-2. They protect the demo's Fireworks key from being scripted into an
  unbounded bill on a public, unauthenticated URL. They are **not** a
  substitute for real auth/quota infrastructure if the demo ever needs to
  scale past one process (e.g. multiple Space replicas), since state is
  not shared across processes.
- **Budget cap semantics:** Tier-0 (deterministic solver) answers are
  always free and always available, even after the daily cap is hit —
  only requests that would trigger a paid model call return `503` once
  the cap is reached. This keeps the demo *looking* alive (zero-token
  prompts still work) instead of going fully dark for the rest of the day.
- **API key rotation:** the Fireworks API key used during development was
  shared in a chat channel while building this project. Per `SECURITY.md`'s
  pre-release checklist, **rotate that key after the hackathon** even
  though the secret-scanning audit found zero occurrences of it in git
  history or the working tree — a chat share is cheap insurance to close
  out regardless.
- **Health/observability:** `GET /healthz` is a liveness probe (used by
  container orchestrators); `GET /api/stats` reports cumulative token
  spend, route-tier distribution, and savings for the process's lifetime —
  useful as a lightweight operational dashboard during the demo window.
  Route decisions and retry events are logged to stderr (`adapter.py` and
  `client.py`), never mixed into the JSON output/response bodies.
- **Demo-mode fallback:** if `FIREWORKS_API_KEY` is ever unset in the Space
  environment (e.g. secret misconfigured), `webapp.py` boots anyway in
  Tier-0-only demo mode rather than crashing — model-routed prompts return
  a clear `503` instead of a 500 or a hung request.
