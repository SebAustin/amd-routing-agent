# ADR-1: Tiered cascade over single-model routing

## Context

The leaderboard scores token count and accuracy jointly (`PLAN.md` §1,
SC1–SC3). A single strong model for every task would maximize accuracy but
spend tokens on tasks a regex or a cheap model could solve just as
correctly.

## Decision

Route every task through a 3-tier cascade — deterministic solver (free) →
cheapest adequate model → single escalation to the strongest model —
rather than a uniform model choice or a multi-round agent/self-verification
loop. Implemented in `src/routing_agent/router.py::route()`.

## Consequences

- 32.5% of the 200-task evalset resolves at zero tokens (Tier 0).
- At most 2 model calls per task, ever — a known worst-case cost bound,
  no runaway loops.
- Adds routing-logic surface area (classifier + confidence gate) that
  needs its own test coverage and can misroute; mitigated by
  precision-first Tier-0 solvers (fire only when self-validated) and CI
  regression tests over `classifier.py` / `tests/test_classifier.py`.
