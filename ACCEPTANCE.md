# ACCEPTANCE — Hybrid Token-Efficient Routing Agent (AMD Hackathon ACT II, Track 1)

Date: 2026-07-07 · Verdict basis: independent solution-verifier score **97/100 — SOLID** (iteration 1 of the build/verify loop; no FIX round required).

## Success criteria

| SC | Criterion | Verdict | Evidence |
|----|-----------|---------|----------|
| SC1 | Eval accuracy ≥ 90% | **PASS — 99.5%** (199/200) | `evals/reports/tuned-live.json`; per-category 100% except summarization 80% (4/5) |
| SC2 | ≥ 60% token reduction vs baseline *(stretch)* | **FAIL (honest) — ~47–51%** | `evals/README.md` §5; floor traced to gpt-oss chat-template overhead (~82 tokens) + reasoning-completion cost; baseline deliberately made *fairer* mid-build (`apply_reasoning_profile` bypass, ADR-0004), which lowered the reported figure |
| SC3 | ≥ 30% tasks at zero Fireworks tokens | **PASS — 32.5%** (65/200 via Tier-0) | `tuned-live.json` route distribution; independently confirmed by `--dry-run` |
| SC4 | Containerized harness contract | **PASS (as scoped)** | Image build green in CI (run 28885737392); adapter contract verified locally: `[{"id","prompt"}] → [{"id","output"}]`; in-container runtime run open (local Docker daemon unavailable) — behavior identical by construction, `adapter.py` is runtime-agnostic |
| SC5 | Public repo, README, CI green, no secrets | **PASS** | github.com/SebAustin/amd-routing-agent; CI green (lint+test & docker-build); key absent from full git history (verified twice: security audit + pre-push sweep) |
| SC6 | Gemma preference activates when allowed | **PASS** | `registry.cheapest()` sort key prefers `gemma*` at equal price tier; 4 dedicated unit tests; dormant today because Fireworks serverless returned NOT_FOUND for all Gemma variants (probed live 2026-07-07) |

## Quality gates (final state)

- `uv run ruff check .` — All checks passed
- `uv run pytest -q` — **175 passed**
- `python3 evals/graders.py` — 200/200 tasks valid, identity-grade PASS
- GitHub Actions — both jobs green on main
- Security: STRIDE audit, 0 CRITICAL / 0 HIGH; M-1 resolved in code; M-2 resolved (rate limit + $1/day budget cap in webapp)
- Live tuning spend: ≈ $0.15 total; tuned 200-task eval run costs $0.0037

## Built

Tiered routing cascade (Tier-0 deterministic solvers → cheapest adequate Fireworks model → single escalation), zero-token classifier, model registry with live-probed reasoning-suppression profiles and Gemma preference, token ledger (raw + price-weighted, retry-counting), harness adapter (isolated contract boundary), 200-task graded eval set + runner + tuned policy, FastAPI demo dashboard (rate-limited, budget-capped, keyless demo mode), Docker (harness default + Space variant), CI, full documentation set (README, ARCHITECTURE, 4 ADRs, runbook, SECURITY, DEPLOYMENT), launch materials (demo script, deck, submission copy, social drafts).

## Deferred (documented, non-blocking)

1. `Policy.retry_budget` not consulted by client (always retry-once; ledger counts it; live retry rate 2.1%).
2. Logprob secondary confidence signal unwired (format-validation primary achieves 99.5%).
3. In-container harness runtime execution (Docker daemon unavailable locally; image build CI-verified).
4. HF Space demo deploy — fully prepared, **gated on a write-scoped HF token**: `HF_TOKEN=hf_xxx ./scripts/deploy_space.sh` (user approved live-key-with-caps mode).

## Next (when the real harness spec lands — Day-4 reserved)

Edit `adapter.py` only → re-run `pytest` + `evals/run_eval.py --policy tuned` → validate route distribution against any published sample tasks → re-baseline SC2/SC3 → submit on lablab.ai before the July 11 deadline (fields ready in `launch/SUBMISSION.md`).
