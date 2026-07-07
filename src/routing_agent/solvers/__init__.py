"""Tier-0 deterministic solvers: zero-token, precision-first task resolvers.

Each solver module exposes `try_solve(task, task_type) -> SolverResult`. A
solver returns `confident=True` only when it can parse the entire ask
unambiguously; any partial match, ambiguity, or parse failure returns
`SolverResult(answer=None, confident=False)` so the router falls through to
Tier 1 rather than risk a wrong zero-token answer.
"""

from __future__ import annotations

from pydantic import BaseModel


class SolverResult(BaseModel):
    """Outcome of a Tier-0 solve attempt."""

    answer: str | None = None
    confident: bool = False
