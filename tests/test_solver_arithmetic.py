"""Tests for the arithmetic Tier-0 solver: exact expectations plus
adversarial near-misses that must return confident=False.
"""

from __future__ import annotations

from routing_agent.classifier import TaskType
from routing_agent.models import Task
from routing_agent.solvers import arithmetic


def _task(prompt: str) -> Task:
    return Task(id="t1", prompt=prompt)


def test_solves_simple_addition():
    result = arithmetic.try_solve(_task("2 + 2"), TaskType.ARITHMETIC)
    assert result.confident is True
    assert result.answer == "4"


def test_solves_operator_precedence():
    result = arithmetic.try_solve(_task("what is 3 + 4 * 2"), TaskType.ARITHMETIC)
    assert result.confident is True
    assert result.answer == "11"


def test_solves_parentheses_and_decimals():
    result = arithmetic.try_solve(_task("(2.5 + 1.5) * 2"), TaskType.ARITHMETIC)
    assert result.confident is True
    assert result.answer == "8"


def test_solves_floor_division_and_modulo():
    assert arithmetic.try_solve(_task("17 // 5"), TaskType.ARITHMETIC).answer == "3"
    assert arithmetic.try_solve(_task("17 % 5"), TaskType.ARITHMETIC).answer == "2"


def test_solves_exponent():
    result = arithmetic.try_solve(_task("2 ** 10"), TaskType.ARITHMETIC)
    assert result.answer == "1024"


def test_solves_percent_of_worded_form():
    result = arithmetic.try_solve(_task("What is 17% of 340?"), TaskType.ARITHMETIC)
    assert result.confident is True
    assert result.answer == "57.8"


def test_returns_not_confident_on_division_by_zero():
    result = arithmetic.try_solve(_task("5 / 0"), TaskType.ARITHMETIC)
    assert result.confident is False
    assert result.answer is None


def test_returns_not_confident_on_non_arithmetic_task_type():
    result = arithmetic.try_solve(_task("2 + 2"), TaskType.GENERAL)
    assert result.confident is False


def test_returns_not_confident_on_prose_wrapped_expression():
    # Adversarial near-miss: extra prose the extractor can't strip cleanly.
    result = arithmetic.try_solve(
        _task("I have 2 apples and John has 3, what is the total count of fruit"),
        TaskType.ARITHMETIC,
    )
    assert result.confident is False
    assert result.answer is None


def test_returns_not_confident_on_disallowed_function_call():
    # Adversarial: attempts code injection via a call expression.
    result = arithmetic.try_solve(_task("__import__('os').system('ls')"), TaskType.ARITHMETIC)
    assert result.confident is False
    assert result.answer is None


def test_returns_not_confident_on_empty_prompt():
    result = arithmetic.try_solve(_task(""), TaskType.ARITHMETIC)
    assert result.confident is False


def test_returns_not_confident_on_multiple_questions():
    result = arithmetic.try_solve(_task("What is 2+2? Also what is 3+3?"), TaskType.ARITHMETIC)
    assert result.confident is False
