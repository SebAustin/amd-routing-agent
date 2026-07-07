"""Minimal per-task-type prompt templates: answer-only contracts, per-type
max_tokens, and stop sequences.

No system message is used unless it demonstrably saves output tokens by
tightening the answer contract (e.g. classification/multiple-choice benefit
from "answer with only the label"; open-ended types like summarization do
not need one).
"""

from __future__ import annotations

from dataclasses import dataclass

from routing_agent.classifier import TaskType
from routing_agent.config import Policy


@dataclass(frozen=True)
class PromptSpec:
    """A rendered request shape for one Tier-1/Tier-2 model call."""

    messages: list[dict[str, str]]
    max_tokens: int
    stop: list[str] | None


# system_text=None means no system message is sent at all.
_SYSTEM_TEXT: dict[TaskType, str | None] = {
    TaskType.ARITHMETIC: "Answer with only the final number.",
    TaskType.DATE_MATH: "Answer with only the date or value requested, no explanation.",
    TaskType.STRING_OP: "Answer with only the resulting string, no explanation.",
    TaskType.UNIT_CONVERSION: "Answer with only the converted number, no units unless asked.",
    TaskType.EXTRACTION: "Answer with only the extracted value(s), no explanation.",
    TaskType.CLASSIFICATION: "Answer with only the label.",
    TaskType.MULTIPLE_CHOICE: "Answer with only the letter of the correct choice.",
    TaskType.SHORT_QA: "Answer in as few words as possible.",
    TaskType.CODE: None,
    TaskType.SUMMARIZATION: None,
    TaskType.GENERAL: None,
}

# Single-line-answer types get a newline stop sequence to cut trailing
# rambling; open-ended types (code, summarization, general) do not.
_SINGLE_LINE_TYPES = frozenset(
    {
        TaskType.ARITHMETIC,
        TaskType.DATE_MATH,
        TaskType.STRING_OP,
        TaskType.UNIT_CONVERSION,
        TaskType.EXTRACTION,
        TaskType.CLASSIFICATION,
        TaskType.MULTIPLE_CHOICE,
        TaskType.SHORT_QA,
    }
)


def build_prompt(task_type: TaskType, prompt_text: str, policy: Policy) -> PromptSpec:
    """Render the minimal messages/max_tokens/stop for a Tier-1/Tier-2 call.

    `policy` supplies the per-task-type max_tokens (with the `general`
    bucket as fallback); the system text and stop sequences are fixed
    per-type contracts defined above.
    """
    system_text = _SYSTEM_TEXT.get(task_type)
    messages: list[dict[str, str]] = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.append({"role": "user", "content": prompt_text})

    stop = ["\n"] if task_type in _SINGLE_LINE_TYPES else None

    return PromptSpec(
        messages=messages,
        max_tokens=policy.max_tokens_for(task_type.value),
        stop=stop,
    )
