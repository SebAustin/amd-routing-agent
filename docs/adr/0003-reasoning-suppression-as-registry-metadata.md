# ADR-3: Reasoning suppression as first-class registry metadata

## Context

Live probing against the real Fireworks API (`PLAN.md` §2) found
`gpt-oss-20b`/`120b` burn completion-token budget on hidden
`reasoning_content` before emitting any visible answer — with a tight
`max_tokens` cap, the first call returns no content at all. Different
models need different suppression params (`reasoning_effort`) and
different minimum caps to avoid truncating mid-reasoning
(`deepseek-v4-pro` accepts `"none"`; `gpt-oss` rejects it and needs
`"low"` plus a larger floor instead).

## Decision

Store `reasoning_profile: dict[str, object]` and `min_viable_max_tokens:
int` directly on each `ModelInfo` record in `src/routing_agent/registry.py`
(`KNOWN_MODELS`). `client.py::FireworksClient.complete()` merges the
profile into every request and floors the caller-supplied `max_tokens`
against the model's minimum, rather than handling this as call-site
special-casing or one global setting.

## Consequences

- Adding a new model requires only one `ModelInfo` entry with an
  eval-tuned profile; `router.py` and `prompts.py` stay model-agnostic.
- Profiles are empirically tuned constants — `registry.py`'s comments cite
  the exact probed completion-token counts that motivated each value
  (e.g. `min_viable_max_tokens` 128 vs. 96 for gpt-oss, tuned after a
  truncated reasoning-channel leak). These can go stale if Fireworks
  changes a model's chat template and need periodic re-verification via
  `evals/run_eval.py`'s tuning ladder.
- `client.complete()` gained an `apply_reasoning_profile: bool` parameter
  so the eval harness's `--baseline` mode can bypass this tuning
  entirely (see ADR-4).
