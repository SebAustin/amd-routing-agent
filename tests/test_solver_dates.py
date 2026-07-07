"""Tests for the date-math Tier-0 solver."""

from __future__ import annotations

from routing_agent.classifier import TaskType
from routing_agent.models import Task
from routing_agent.solvers import dates


def _task(prompt: str) -> Task:
    return Task(id="t1", prompt=prompt)


def test_solves_days_after():
    result = dates.try_solve(_task("What date is 45 days after March 3, 2026?"), TaskType.DATE_MATH)
    assert result.confident is True
    assert result.answer == "2026-04-17"


def test_solves_days_before():
    result = dates.try_solve(
        _task("What date is 10 days before January 5, 2025?"), TaskType.DATE_MATH
    )
    assert result.confident is True
    assert result.answer == "2024-12-26"


def test_solves_weeks_after():
    result = dates.try_solve(_task("What date is 2 weeks after June 1, 2026?"), TaskType.DATE_MATH)
    assert result.answer == "2026-06-15"


def test_solves_weekday_of_date():
    result = dates.try_solve(_task("What day of the week is July 4, 2026?"), TaskType.DATE_MATH)
    assert result.confident is True
    assert result.answer == "Saturday"


def test_solves_days_between():
    result = dates.try_solve(
        _task("How many days between January 1, 2026 and January 31, 2026?"),
        TaskType.DATE_MATH,
    )
    assert result.confident is True
    assert result.answer == "30"


def test_returns_not_confident_on_wrong_task_type():
    result = dates.try_solve(_task("45 days after March 3"), TaskType.GENERAL)
    assert result.confident is False


def test_returns_not_confident_on_unparseable_date():
    result = dates.try_solve(_task("What date is 45 days after blorptown?"), TaskType.DATE_MATH)
    assert result.confident is False
    assert result.answer is None


def test_returns_not_confident_on_ambiguous_prompt():
    # Adversarial: no recognizable date-math shape at all.
    result = dates.try_solve(
        _task("Tell me something interesting about dates."), TaskType.DATE_MATH
    )
    assert result.confident is False


def test_solves_days_from_to_phrasing():
    # Regression: "how many days ... from X to Y" (distinct from "between X
    # and Y") previously fell through to Tier 1, where the model applied
    # inconsistent calendar-day-count semantics instead of a plain date
    # difference (found via eval audit, dates-015: 365 vs expected 364).
    result = dates.try_solve(
        _task("How many days are there from January 1, 2025 to December 31, 2025?"),
        TaskType.DATE_MATH,
    )
    assert result.confident is True
    assert result.answer == "364"


def test_solves_days_from_to_phrasing_leap_year_span():
    result = dates.try_solve(
        _task("How many days are there from February 1, 2025 to February 1, 2026?"),
        TaskType.DATE_MATH,
    )
    assert result.confident is True
    assert result.answer == "365"
