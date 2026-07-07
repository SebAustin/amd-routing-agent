"""Tiered routing cascade (PLAN.md §3):

  classify -> Tier 0 (deterministic solvers, 0 tokens)
           -> Tier 1 (cheapest adequate allowed model, confidence-gated)
           -> Tier 2 (single escalation to strongest allowed model)

Never more than 2 model calls per task, plus bounded per-task-type retries
inside `FireworksClient.complete`. Every decision is logged via the
`logging` module for eval-time route-distribution analysis.
"""

from __future__ import annotations

import logging

from routing_agent.classifier import TaskType, classify
from routing_agent.client import FireworksClient
from routing_agent.config import Policy
from routing_agent.models import RouteDecision, Task
from routing_agent.prompts import build_prompt
from routing_agent.registry import ModelInfo, cheapest, strongest
from routing_agent.solvers import SolverResult, arithmetic, dates, extraction, strings, units

logger = logging.getLogger(__name__)

# TaskType -> solver module, in the order they should be attempted. Only one
# solver is relevant per classified type today, but this stays a list so a
# future type can be backed by multiple candidate solvers.
_SOLVERS_BY_TYPE: dict[TaskType, list] = {
    TaskType.ARITHMETIC: [arithmetic],
    TaskType.DATE_MATH: [dates],
    TaskType.STRING_OP: [strings],
    TaskType.UNIT_CONVERSION: [units],
    TaskType.EXTRACTION: [extraction],
}

_CAPABILITY_BY_TYPE: dict[TaskType, str] = {
    TaskType.ARITHMETIC: "math",
    TaskType.DATE_MATH: "math",
    TaskType.STRING_OP: "general",
    TaskType.UNIT_CONVERSION: "math",
    TaskType.EXTRACTION: "extraction",
    TaskType.CLASSIFICATION: "classification",
    TaskType.MULTIPLE_CHOICE: "classification",
    TaskType.SHORT_QA: "general",
    TaskType.CODE: "code",
    TaskType.SUMMARIZATION: "long_form",
    TaskType.GENERAL: "general",
}


class RouterResult:
    """The final answer for one task plus the route decision that produced it."""

    def __init__(self, output: str, route: RouteDecision) -> None:
        self.output = output
        self.route = route


def _try_tier0(task: Task, task_type: TaskType) -> SolverResult:
    for solver_module in _SOLVERS_BY_TYPE.get(task_type, []):
        result = solver_module.try_solve(task, task_type)
        if result.confident and result.answer is not None:
            return result
    return SolverResult(answer=None, confident=False)


def _cross_check(task_type: TaskType, task: Task, candidate_answer: str) -> bool:
    """SECONDARY confidence signal: re-run the Tier-0 solver (when one exists
    for this type) against the same prompt and compare to the model's
    answer. Used only as a corroborating signal, never to reject the model's
    answer outright when no solver exists for the type.
    """
    solvers = _SOLVERS_BY_TYPE.get(task_type)
    if not solvers:
        return True
    tier0_result = _try_tier0(task, task_type)
    if not tier0_result.confident or tier0_result.answer is None:
        return True
    return _normalize(tier0_result.answer) == _normalize(candidate_answer)


def _normalize(value: str) -> str:
    return value.strip().strip(".").lower()


def _validate_format(task_type: TaskType, answer: str) -> bool:
    """PRIMARY confidence gate: cheap output-format sanity checks per type."""
    stripped = answer.strip()
    if not stripped:
        return False
    if task_type == TaskType.CLASSIFICATION:
        return len(stripped.split()) <= 3
    if task_type == TaskType.MULTIPLE_CHOICE:
        return len(stripped) <= 3
    if task_type in (TaskType.ARITHMETIC, TaskType.UNIT_CONVERSION):
        return any(c.isdigit() for c in stripped)
    return True


def route(
    task: Task,
    client: FireworksClient,
    allowed_models: list[ModelInfo],
    policy: Policy,
) -> RouterResult:
    """Route a single task through the Tier 0/1/2 cascade and return the answer.

    Raises no exceptions for routing-logic reasons; a task that exhausts all
    tiers still returns the best available Tier-2 output. Errors from the
    underlying HTTP client are allowed to propagate — the adapter's caller is
    responsible for task-level error isolation if the harness requires it.
    """
    task_type = (
        TaskType(task.type) if task.type in TaskType._value2member_map_ else classify(task.prompt)
    )

    tier0_result = _try_tier0(task, task_type)
    if tier0_result.confident and tier0_result.answer is not None:
        route_decision = RouteDecision(tier=0, model=None, task_type=task_type.value)
        logger.info(
            "tier0 solve",
            extra={"task_id": task.id, "task_type": task_type.value, "tier": 0},
        )
        return RouterResult(output=tier0_result.answer, route=route_decision)

    capability = _CAPABILITY_BY_TYPE.get(task_type, "general")
    tier1_model = cheapest(capability, allowed_models)

    if tier1_model is not None:
        prompt_spec = build_prompt(task_type, task.prompt, policy)
        completion = client.complete(
            model_info=tier1_model,
            messages=prompt_spec.messages,
            max_tokens=prompt_spec.max_tokens,
            stop=prompt_spec.stop,
            route=f"tier1:{task.id}",
        )
        answer = completion.content.strip()
        primary_ok = _validate_format(task_type, answer)
        secondary_ok = _cross_check(task_type, task, answer) if primary_ok else False

        if primary_ok and secondary_ok:
            route_decision = RouteDecision(
                tier=1,
                model=tier1_model.id,
                task_type=task_type.value,
                confident=True,
                retried=completion.retried,
            )
            logger.info(
                "tier1 solve",
                extra={
                    "task_id": task.id,
                    "task_type": task_type.value,
                    "tier": 1,
                    "model": tier1_model.id,
                },
            )
            return RouterResult(output=answer, route=route_decision)

        logger.info(
            "tier1 confidence gate failed, escalating",
            extra={"task_id": task.id, "task_type": task_type.value, "model": tier1_model.id},
        )

    tier2_model = strongest(allowed_models)
    if tier2_model is None:
        # No models available at all — return whatever Tier 1 produced (or
        # empty) rather than raising, so the adapter always has an output.
        fallback_answer = answer if tier1_model is not None else ""
        route_decision = RouteDecision(
            tier=1 if tier1_model is not None else 2,
            model=tier1_model.id if tier1_model is not None else None,
            task_type=task_type.value,
            confident=False,
        )
        return RouterResult(output=fallback_answer, route=route_decision)

    prompt_spec = build_prompt(task_type, task.prompt, policy)
    completion = client.complete(
        model_info=tier2_model,
        messages=prompt_spec.messages,
        max_tokens=prompt_spec.max_tokens,
        stop=prompt_spec.stop,
        route=f"tier2:{task.id}",
    )
    route_decision = RouteDecision(
        tier=2,
        model=tier2_model.id,
        task_type=task_type.value,
        confident=True,
        retried=completion.retried,
        escalated=True,
    )
    logger.info(
        "tier2 escalation",
        extra={"task_id": task.id, "task_type": task_type.value, "model": tier2_model.id},
    )
    return RouterResult(output=completion.content.strip(), route=route_decision)
