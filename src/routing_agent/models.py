"""Pydantic data types shared across the routing agent.

These types are the stable boundary between the (unknown) scoring harness and
the rest of the system. `Task` tolerantly accepts several historically-common
field name variants so that `adapter.py` can stay thin; every other module
only ever sees the normalized shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Field names harnesses have been observed to use for the task's primary text.
_PROMPT_ALIASES = ("prompt", "input", "question", "text")


class Task(BaseModel):
    """A single unit of work to route and solve.

    `prompt` is populated from whichever of `prompt`/`input`/`question`/`text`
    is present in the source payload (first match wins). `type` is an optional
    harness-supplied hint; when absent the classifier infers it.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    prompt: str
    type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _populate_prompt_from_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("prompt"):
            return data
        normalized = dict(data)
        for alias in _PROMPT_ALIASES:
            value = data.get(alias)
            if isinstance(value, str) and value.strip():
                normalized["prompt"] = value
                break
        return normalized


class RouteDecision(BaseModel):
    """Records which tier/model resolved a task, for logging and eval analysis."""

    tier: int
    model: str | None = None
    task_type: str
    confident: bool = True
    retried: bool = False
    escalated: bool = False


class Result(BaseModel):
    """The output for a single task plus routing metadata (never serialized to
    the harness-facing results.json — adapter strips metadata before writing).
    """

    id: str
    output: str
    route: RouteDecision | None = None


class CallRecord(BaseModel):
    """A single Fireworks API call, as recorded by the TokenLedger."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int = 0
    latency_ms: float = 0.0
    route: str = ""
    retry: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens
