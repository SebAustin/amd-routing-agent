"""Unit conversion solver: length, mass, temperature, and data-size units.

Only fires on the canonical "convert X <unit> to <unit>" shape with a single
numeric value and two recognized unit tokens; anything else (multi-step
conversions, unrecognized units) falls through with confident=False.
"""

from __future__ import annotations

import re

from routing_agent.classifier import TaskType
from routing_agent.models import Task
from routing_agent.solvers import SolverResult

_CONVERT_RE = re.compile(
    r"convert\s+(?P<value>-?\d+(?:\.\d+)?)\s*(?P<from>[a-zA-Z°]+)\s+to\s+(?P<to>[a-zA-Z°]+)",
    re.IGNORECASE,
)

# All length/mass/data units normalized to a base unit via a linear factor.
_LENGTH_TO_METERS: dict[str, float] = {
    "mm": 0.001,
    "millimeter": 0.001,
    "millimeters": 0.001,
    "cm": 0.01,
    "centimeter": 0.01,
    "centimeters": 0.01,
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "km": 1000.0,
    "kilometer": 1000.0,
    "kilometers": 1000.0,
    "in": 0.0254,
    "inch": 0.0254,
    "inches": 0.0254,
    "ft": 0.3048,
    "foot": 0.3048,
    "feet": 0.3048,
    "yd": 0.9144,
    "yard": 0.9144,
    "yards": 0.9144,
    "mi": 1609.344,
    "mile": 1609.344,
    "miles": 1609.344,
}

_MASS_TO_GRAMS: dict[str, float] = {
    "mg": 0.001,
    "milligram": 0.001,
    "milligrams": 0.001,
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "kilogram": 1000.0,
    "kilograms": 1000.0,
    "lb": 453.59237,
    "lbs": 453.59237,
    "pound": 453.59237,
    "pounds": 453.59237,
    "oz": 28.349523125,
    "ounce": 28.349523125,
    "ounces": 28.349523125,
}

_DATA_TO_BYTES: dict[str, float] = {
    "b": 1.0,
    "byte": 1.0,
    "bytes": 1.0,
    "kb": 1000.0,
    "mb": 1000.0**2,
    "gb": 1000.0**3,
    "tb": 1000.0**4,
}

_TEMP_UNITS = {"c", "celsius", "f", "fahrenheit", "k", "kelvin"}


def _normalize_unit(unit: str) -> str:
    return unit.strip().lower().rstrip(".")


def _convert_linear(
    value: float, from_unit: str, to_unit: str, table: dict[str, float]
) -> float | None:
    if from_unit not in table or to_unit not in table:
        return None
    base_value = value * table[from_unit]
    return base_value / table[to_unit]


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float | None:
    from_key = from_unit[0]
    to_key = to_unit[0]
    if from_key not in ("c", "f", "k") or to_key not in ("c", "f", "k"):
        return None

    if from_key == "c":
        celsius = value
    elif from_key == "f":
        celsius = (value - 32) * 5.0 / 9.0
    else:
        celsius = value - 273.15

    if to_key == "c":
        return celsius
    if to_key == "f":
        return celsius * 9.0 / 5.0 + 32
    return celsius + 273.15


def _format_result(value: float) -> str:
    rounded = round(value, 4)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


def try_solve(task: Task, task_type: TaskType) -> SolverResult:
    """Attempt to solve a single-hop unit conversion from a canonical prompt."""
    if task_type != TaskType.UNIT_CONVERSION:
        return SolverResult(answer=None, confident=False)

    match = _CONVERT_RE.search(task.prompt.strip())
    if not match:
        return SolverResult(answer=None, confident=False)

    value = float(match.group("value"))
    from_unit = _normalize_unit(match.group("from"))
    to_unit = _normalize_unit(match.group("to"))

    if from_unit in _TEMP_UNITS or to_unit in _TEMP_UNITS:
        result = _convert_temperature(value, from_unit, to_unit)
    elif from_unit in _LENGTH_TO_METERS or to_unit in _LENGTH_TO_METERS:
        result = _convert_linear(value, from_unit, to_unit, _LENGTH_TO_METERS)
    elif from_unit in _MASS_TO_GRAMS or to_unit in _MASS_TO_GRAMS:
        result = _convert_linear(value, from_unit, to_unit, _MASS_TO_GRAMS)
    elif from_unit in _DATA_TO_BYTES or to_unit in _DATA_TO_BYTES:
        result = _convert_linear(value, from_unit, to_unit, _DATA_TO_BYTES)
    else:
        result = None

    if result is None:
        return SolverResult(answer=None, confident=False)

    return SolverResult(answer=_format_result(result), confident=True)
