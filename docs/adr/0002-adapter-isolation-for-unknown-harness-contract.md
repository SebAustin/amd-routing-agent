# ADR-2: Adapter isolation for the unknown harness contract

## Context

The real scoring harness's I/O contract (schema, field names,
`ALLOWED_MODELS` format) was unpublished at build time (`ASSUMPTIONS.md`
#1–#3). Guessing wrong anywhere in the core would mean a scattered rewrite
under a hard July 11 deadline.

## Decision

Confine 100% of harness-facing I/O to `src/routing_agent/adapter.py` —
file/stdin reading, JSON parsing, alias-tolerant field mapping (via the
`Task` pydantic model's `_populate_prompt_from_aliases` validator in
`models.py`), and `results.json` writing. Every other module (`router.py`,
`classifier.py`, `solvers/`, `registry.py`) only ever sees the normalized
`Task`/`Result` pydantic types.

## Consequences

- If the real spec differs from the assumed `/input/tasks.json` →
  `/output/results.json` contract, only `adapter.py` changes; router,
  classifier, solvers, registry, and their tests are untouched
  (`RUNBOOK.md` "when the real harness spec lands" checklist).
- Adds one indirection layer (`_read_tasks`/`_parse_tasks`) that must stay
  in sync with `Task`'s alias list (`prompt`/`input`/`question`/`text`).
- `MAX_INPUT_BYTES`/`MAX_TASKS` guards live at this same boundary
  (`SECURITY.md` M-1), keeping all input-trust decisions in one file.
