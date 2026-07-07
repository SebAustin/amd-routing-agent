"""Date arithmetic solver using python-dateutil.

Handles: "N days/weeks/months after/before <date>", "what day of the week is
<date>", and "how many days between <date> and <date>". Only fires when the
prompt matches one of these shapes exactly and all date tokens parse
unambiguously; anything looser falls through to Tier 1.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta

from routing_agent.classifier import TaskType
from routing_agent.models import Task
from routing_agent.solvers import SolverResult

_UNIT_TO_KWARG = {
    "day": "days",
    "days": "days",
    "week": "weeks",
    "weeks": "weeks",
    "month": "months",
    "months": "months",
    "year": "years",
    "years": "years",
}

_OFFSET_RE = re.compile(
    r"(?P<num>\d+)\s+(?P<unit>days?|weeks?|months?|years?)\s+"
    r"(?P<direction>after|before)\s+(?P<date>.+?)\s*\??$",
    re.IGNORECASE,
)

_WEEKDAY_RE = re.compile(
    r"(?:what\s+day\s+of\s+the\s+week|which\s+weekday|weekday)\s+"
    r"(?:is|was|falls\s+on)?\s*(?P<date>.+?)\s*\??$",
    re.IGNORECASE,
)

_BETWEEN_RE = re.compile(
    r"how\s+many\s+days\s+(?:are\s+)?between\s+(?P<date1>.+?)\s+and\s+(?P<date2>.+?)\s*\??$",
    re.IGNORECASE,
)

_WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def _parse_date(text: str) -> date | None:
    cleaned = text.strip().strip("?.!,")
    if not cleaned:
        return None
    try:
        parsed = dateutil_parser.parse(cleaned, fuzzy=False, default=datetime(2000, 1, 1))
    except (ValueError, OverflowError):
        return None
    return parsed.date()


def try_solve(task: Task, task_type: TaskType) -> SolverResult:
    """Attempt to solve a date-math task deterministically.

    Only fires for the three supported shapes (offset, weekday-of, days-
    between); any prompt that doesn't cleanly match one of these regexes, or
    whose date tokens fail to parse, returns confident=False.
    """
    if task_type != TaskType.DATE_MATH:
        return SolverResult(answer=None, confident=False)

    prompt = task.prompt.strip()

    offset_match = _OFFSET_RE.search(prompt)
    if offset_match:
        base = _parse_date(offset_match.group("date"))
        if base is None:
            return SolverResult(answer=None, confident=False)
        amount = int(offset_match.group("num"))
        unit_kwarg = _UNIT_TO_KWARG[offset_match.group("unit").lower()]
        if offset_match.group("direction").lower() == "before":
            amount = -amount
        result = base + relativedelta(**{unit_kwarg: amount})
        return SolverResult(answer=result.isoformat(), confident=True)

    weekday_match = _WEEKDAY_RE.search(prompt)
    if weekday_match:
        target = _parse_date(weekday_match.group("date"))
        if target is None:
            return SolverResult(answer=None, confident=False)
        return SolverResult(answer=_WEEKDAY_NAMES[target.weekday()], confident=True)

    between_match = _BETWEEN_RE.search(prompt)
    if between_match:
        first = _parse_date(between_match.group("date1"))
        second = _parse_date(between_match.group("date2"))
        if first is None or second is None:
            return SolverResult(answer=None, confident=False)
        delta_days = abs((second - first).days)
        return SolverResult(answer=str(delta_days), confident=True)

    return SolverResult(answer=None, confident=False)
