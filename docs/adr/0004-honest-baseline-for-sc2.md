# ADR-4: Honest baseline for SC2 (`apply_reasoning_profile` bypass)

## Context

SC2 (≥60% Fireworks token reduction vs. a naive baseline policy, stretch
target — `PLAN.md` §1) needs a believable "naive deployment" comparison
bar: strongest allowed model, default/generic prompt, no per-type tuning.
A baseline that silently reused this router's own reasoning-suppression
profiles would overstate real-world savings, since it would not reflect
what an actually-unoptimized deployment costs.

## Decision

Make `apply_reasoning_profile` a first-class parameter of
`client.py::FireworksClient.complete()`, not a special-cased hack.
`evals/run_eval.py --baseline` passes `apply_reasoning_profile=False`
explicitly so the comparison run reflects a genuinely naive deployment
(strongest model, `"Answer the following."` prompt, `max_tokens=512`, no
reasoning suppression) rather than "generic prompt + this router's own
tuning."

## Consequences

- The measured baseline (163–174 tokens/task on a stratified 60-task
  sample, extrapolated to ~32,600–34,800 tokens/200 tasks) vs. the tuned
  live run (17,157 tokens/200 tasks, `evals/reports/tuned-live.json`)
  gives an honest **~47–51% reduction** — short of the 60% stretch target,
  but defensible under scrutiny: the comparison bar isn't quietly
  benefiting from the same optimizations being measured against it.
- Adds one boolean parameter to the client's request-building API surface,
  in exchange for keeping both code paths (tuned and baseline) in the same
  function instead of duplicating request-shaping logic.
- Documented plainly in `evals/README.md` "Tuning notes" #5 rather than
  only in code comments, so the honesty of the comparison is auditable
  without reading `client.py`.
