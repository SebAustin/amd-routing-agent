"""Regex-based extraction solver: emails, URLs, phone numbers, numbers, dates.

Only fires when the prompt unambiguously asks for exactly one category of
entity from an embedded text blob and the regex finds exactly one match (or
the ask is explicitly plural, in which case all matches are joined). Multiple
categories requested at once, or zero matches, fall through with
confident=False.
"""

from __future__ import annotations

import re

from routing_agent.classifier import TaskType
from routing_agent.models import Task
from routing_agent.solvers import SolverResult

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://[^\s,;\"')\]]+")
_PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# Ordered most-specific-first: "phone number" must be checked (and, if
# matched, exclusively used) before the generic "number" pattern, since the
# latter's word boundary matches inside "phone number" too.
_ASK_PATTERNS: tuple[tuple[re.Pattern[str], re.Pattern[str], bool], ...] = (
    (re.compile(r"\bemails?\b", re.IGNORECASE), _EMAIL_RE, True),
    (re.compile(r"\burls?\b|\blinks?\b", re.IGNORECASE), _URL_RE, True),
    (re.compile(r"\bphone numbers?\b", re.IGNORECASE), _PHONE_RE, True),
    (re.compile(r"\bdates?\b", re.IGNORECASE), _ISO_DATE_RE, True),
    (
        re.compile(r"(?<!phone )(?<!phone)\bnumbers?\b", re.IGNORECASE),
        _NUMBER_RE,
        True,
    ),
)

_PLURAL_HINT_RE = re.compile(r"\ball\b|\bevery\b|\bemails\b|\burls\b|\bnumbers\b", re.IGNORECASE)

# Splits "extract the email from: <blob>" style prompts from their source
# text. Word-boundary anchored so "from"/"in" don't match inside other words
# (e.g. "Find"); greedy search finds the rightmost separator so a leading
# "Find the phone number in: ..." splits on the colon, not the first "in".
_SOURCE_SPLIT_RE = re.compile(r"(?:\bfrom\b|\bin\b|:)\s*[\"']?(?P<blob>.+)$", re.DOTALL)


def _find_source_text(prompt: str) -> str:
    last_match = None
    for match in _SOURCE_SPLIT_RE.finditer(prompt):
        last_match = match
    return last_match.group("blob") if last_match else prompt


def try_solve(task: Task, task_type: TaskType) -> SolverResult:
    """Attempt to extract a single unambiguous entity category from the prompt.

    Requires the ask to name exactly one supported category (email/url/
    phone/date/number); if more than one category keyword appears, or the
    regex finds no matches, the solver declines.
    """
    if task_type != TaskType.EXTRACTION:
        return SolverResult(answer=None, confident=False)

    prompt = task.prompt.strip()
    matched_categories = [
        (ask_re, entity_re, is_plural)
        for ask_re, entity_re, is_plural in _ASK_PATTERNS
        if ask_re.search(prompt)
    ]
    if len(matched_categories) != 1:
        return SolverResult(answer=None, confident=False)

    _, entity_re, _ = matched_categories[0]
    source_text = _find_source_text(prompt)
    matches = entity_re.findall(source_text)
    if not matches:
        return SolverResult(answer=None, confident=False)

    wants_all = bool(_PLURAL_HINT_RE.search(prompt))
    if wants_all or len(matches) > 1:
        return SolverResult(answer=", ".join(matches), confident=True)

    return SolverResult(answer=matches[0], confident=True)
