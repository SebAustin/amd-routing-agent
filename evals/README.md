# Evals

200 tasks in `evalset/*.jsonl` (one file/category), per PLAN.md §3 / ASSUMPTIONS.md #13.

| category | count | grader(s) | category | count | grader(s) |
|---|---|---|---|---|---|
| arithmetic | 35 | numeric | multiple_choice | 20 | choice |
| classification | 30 | normalized | short_qa | 15 | normalized |
| dates | 25 | normalized/numeric/exact | units | 15 | numeric |
| extraction | 25 | exact/normalized/numeric | code | 10 | normalized/exact/numeric |
| strings | 20 | exact/numeric/normalized | summarization | 5 | contains_all |

Graders (`graders.py`, stdlib-only): `exact` strips whitespace; `normalized` casefolds + strips diacritics/punctuation/articles; `numeric` parses first number (commas/%/currency) within tolerance (`grader_args.tolerance` abs, else rel 1e-6); `contains_all` requires all `keywords` present (case-insensitive); `choice` extracts A-D from messy text.

Self-check: `python3 evals/graders.py` (validates schema + ids, identity-grades every task, prints per-category counts).

## Running the eval suite

`run_eval.py` routes every task in `evalset/` through the router under a named policy
(`evals/policies/<name>.yaml`), grades each answer, and reports accuracy, token totals, and route
distribution. `.env` is read manually (no `python-dotenv` dependency) via `env_loader.py`.

```bash
# Full cascade against the real Fireworks API (writes evals/reports/<policy>-live.json)
uv run python evals/run_eval.py --policy tuned

# No network — Tier-0/classifier only, measures Tier-0 coverage for free
uv run python evals/run_eval.py --policy tuned --dry-run

# Filter/limit
uv run python evals/run_eval.py --policy tuned --categories arithmetic,dates
uv run python evals/run_eval.py --policy tuned --limit 20

# Baseline: every task -> strongest allowed model, generic prompt, max_tokens=512,
# registry reasoning-suppression profile explicitly bypassed (a naive/untuned
# deployment would not carry the router's own tuning) — this is the SC2 comparison
# bar. A stratified subset (proportional per-category sampling) keeps live-API cost
# small; extrapolate tokens/task * 200 for the full-set comparison.
uv run python evals/run_eval.py --baseline --limit 60 --stratified --policy tuned
```

Default `ALLOWED_MODELS` for local runs (PLAN.md §2 live-callable set), used when the env var is
unset:

```
accounts/fireworks/models/gpt-oss-20b,accounts/fireworks/models/gpt-oss-120b,accounts/fireworks/models/deepseek-v4-flash,accounts/fireworks/models/deepseek-v4-pro,accounts/fireworks/models/glm-5p1
```

Concurrency: live/baseline runs use a `ThreadPoolExecutor` (default 8 workers, `--concurrency` to
override); individual task failures are recorded as wrong answers + an error string rather than
crashing the run.

## Policies

- `policies/default.yaml` — original policy values (max_tokens/thresholds), unchanged by this
  tuning pass.
- `policies/tuned.yaml` — winner of the eval-ladder tuning pass. Same max_tokens values as
  `default.yaml` (see the file's header comment for why per-type caps stopped mattering once they
  clear each Tier-1 model's `min_viable_max_tokens` floor); the real wins were in
  `registry.py` (reasoning-suppression profiles, floor sizing), `prompts.py` (CODE/SUMMARIZATION
  system contracts), `classifier.py` (8 regex bugs), and the Tier-0 solvers (4 precision bugs) —
  all covered by regression tests in `tests/`.

**Note on the committed reports**: `evals/reports/default-*.json` and `tuned-*.json` were both
generated *after* the classifier/registry/prompt/solver fixes below (the `default` and `tuned`
policy YAMLs hold identical values, so a `--policy default` run exercises the same fixed code —
the two report sets are not a true before/after comparison, just two labeled runs of the same
final state, run minutes apart with the usual thread-scheduling/Tier-2-escalation jitter that
explains their small numeric differences). The genuine "before" numbers below (91.5% accuracy,
18,869 raw tokens, 61/200 zero-token) come from an interactive run captured before any fix was
applied and are not backed by a committed JSON file; treat them as directionally accurate,
not byte-exact evidence.

## Tuning notes (eval ladder, PLAN.md §3 step d)

1. **Dry-run coverage** (`tuned-dry-run.json`): Tier-0 solved 61/200 (30.5%) tasks pre-tuning,
   65/200 (32.5%) post-tuning (`tuned-dry-run.json`'s own numbers) — both clear SC3's ≥30%
   zero-token target.
2. **Live, pre-tuning** (not committed as a separate report — see the note above): 91.5% accuracy,
   18,869 raw tokens, before the classifier/prompt/registry fixes in this session's commits.
3. **Live tuned** (`tuned-live.json`, also `default-live.json` since both policies share values):
   99.5% accuracy after fixes (see commit history / report header comments for the full list). One
   residual failure: `summarization-003` — the model's correct paraphrase drops the literal
   keyword "declin[e/ing]" that `contains_all` requires; diminishing returns to chase further on a
   5-task category.
4. **Tier-1 model A/B** (gpt-oss-20b vs deepseek-v4-flash on classification+short_qa+extraction,
   70 tasks): gpt-oss-20b 70/70 correct; deepseek-v4-flash 35/70 — it inlines chain-of-thought
   ("We need to extract...") into `content` under the answer-only system prompt used for these
   types, which fails exact/normalized grading even when the right value appears in the prose.
   Confirms the registry's price-driven `cheapest()` choice (gpt-oss-20b, lower blended price) is
   also the accuracy-correct choice here — no change made.
5. **Baseline extrapolation**: baseline mode explicitly disables the registry's reasoning
   suppression (`apply_reasoning_profile=False` in `client.complete()`) so it reflects a genuinely
   naive deployment, not "generic prompt + our own tuning". Stratified 60-task baseline runs
   measured 163-174 tokens/task (deepseek-v4-pro, unsuppressed reasoning) => ~32,600-34,800 tokens
   extrapolated to 200 tasks, vs the tuned live run's 17,157 measured tokens: **~47-51% token
   reduction**. Short of the 60% stretch target (SC2); the tuned cascade's remaining cost is
   dominated by gpt-oss's fixed ~82-token chat-template overhead plus the
   ~96-128-completion-token floor needed to let its hidden reasoning channel complete without
   leaking/truncating (verified: lowering the floor reintroduces the exact truncation bug fixed in
   this pass; policy-level `max_tokens` below that floor has zero effect since the client floors
   the request either way and models never bill unused budget).
