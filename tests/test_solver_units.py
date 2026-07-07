"""Tests for the unit-conversion Tier-0 solver."""

from __future__ import annotations

from routing_agent.classifier import TaskType
from routing_agent.models import Task
from routing_agent.solvers import units


def _task(prompt: str) -> Task:
    return Task(id="t1", prompt=prompt)


def test_solves_km_to_miles():
    result = units.try_solve(_task("Convert 10 km to miles"), TaskType.UNIT_CONVERSION)
    assert result.confident is True
    assert result.answer == "6.2137"


def test_solves_celsius_to_fahrenheit():
    result = units.try_solve(_task("Convert 100 C to F"), TaskType.UNIT_CONVERSION)
    assert result.confident is True
    assert result.answer == "212"


def test_solves_fahrenheit_to_celsius():
    result = units.try_solve(_task("Convert 32 F to C"), TaskType.UNIT_CONVERSION)
    assert result.answer == "0"


def test_solves_kg_to_pounds():
    result = units.try_solve(_task("Convert 5 kg to lbs"), TaskType.UNIT_CONVERSION)
    assert result.confident is True
    assert result.answer == "11.0231"


def test_solves_mb_to_gb():
    result = units.try_solve(_task("Convert 2048 MB to GB"), TaskType.UNIT_CONVERSION)
    assert result.confident is True
    assert result.answer == "2.048"


def test_solves_kelvin_to_celsius():
    result = units.try_solve(_task("Convert 300 K to C"), TaskType.UNIT_CONVERSION)
    assert result.answer == "26.85"


def test_returns_not_confident_on_unrecognized_unit():
    result = units.try_solve(_task("Convert 10 furlongs to miles"), TaskType.UNIT_CONVERSION)
    assert result.confident is False
    assert result.answer is None


def test_returns_not_confident_on_mixed_category_units():
    # Adversarial: length unit to mass unit, not a valid single-hop conversion.
    result = units.try_solve(_task("Convert 10 km to kg"), TaskType.UNIT_CONVERSION)
    assert result.confident is False


def test_returns_not_confident_on_wrong_task_type():
    result = units.try_solve(_task("Convert 10 km to miles"), TaskType.GENERAL)
    assert result.confident is False


def test_returns_not_confident_on_missing_convert_keyword():
    result = units.try_solve(_task("10 km is how many miles?"), TaskType.UNIT_CONVERSION)
    assert result.confident is False
