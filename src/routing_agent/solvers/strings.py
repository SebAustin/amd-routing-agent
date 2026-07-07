"""String operation solver: reverse, case conversion, length, counting,
substring extraction, and letter sorting on a quoted or clearly-delimited
target string.

Only fires when the operand string can be unambiguously extracted (quoted,
or following a clear "the string X" / "of X" marker) and the operation is one
of the supported shapes; otherwise falls through with confident=False.
"""

from __future__ import annotations

import re

from routing_agent.classifier import TaskType
from routing_agent.models import Task
from routing_agent.solvers import SolverResult

_QUOTED_RE = re.compile(r"[\"'“”](?P<value>[^\"'“”]*)[\"'“”]")


def _all_quoted_spans(prompt: str) -> list[str]:
    return [m.group("value") for m in _QUOTED_RE.finditer(prompt)]


def _extract_target(prompt: str) -> str | None:
    """Extract the operand string: the *last* quoted span.

    Most operations have exactly one quoted span (the operand itself). The
    count-char-occurrences shape has two ("l" ... "hello") — the character
    to search for, then the source string to search in — so the last quoted
    span is always the operand being operated on.
    """
    spans = _all_quoted_spans(prompt)
    if not spans:
        return None
    return spans[-1]


# "reverse the order of the words" (or "word order") means token-reversal,
# not character-reversal — checked before the generic _REVERSE_RE so the
# more specific shape always wins.
_REVERSE_WORD_ORDER_RE = re.compile(
    r"\breverse\b.*\b(order of the words|word order)\b", re.IGNORECASE
)
_REVERSE_RE = re.compile(r"\breverse\b", re.IGNORECASE)
_UPPER_RE = re.compile(r"\buppercase\b|\bupper[- ]?case\b", re.IGNORECASE)
_LOWER_RE = re.compile(r"\blowercase\b|\blower[- ]?case\b", re.IGNORECASE)
_LENGTH_RE = re.compile(r"how many (?P<unit>letters|characters)\b|\blength of\b", re.IGNORECASE)
_COUNT_CHAR_RE = re.compile(
    r"how many (?:times does |occurrences of )?.*(?:occur|appear)", re.IGNORECASE
)
_COUNT_WORD_RE = re.compile(r"how many words\b", re.IGNORECASE)
_FIRST_N_RE = re.compile(r"first (?P<n>\d+) characters", re.IGNORECASE)
_LAST_N_RE = re.compile(r"last (?P<n>\d+) characters", re.IGNORECASE)
_SORT_RE = re.compile(r"sort the letters", re.IGNORECASE)


def try_solve(task: Task, task_type: TaskType) -> SolverResult:
    """Attempt to solve a string-operation task on a quoted operand.

    Requires the target string to be explicitly quoted in the prompt (no
    heuristic "the rest of the sentence is the string" guessing) so the
    solver never mis-segments prose from the operand.
    """
    if task_type != TaskType.STRING_OP:
        return SolverResult(answer=None, confident=False)

    prompt = task.prompt.strip()

    # Count-char-occurrences has two quoted spans (character, source string)
    # and must be checked before generic target extraction picks the wrong one.
    if _COUNT_CHAR_RE.search(prompt):
        spans = _all_quoted_spans(prompt)
        if len(spans) == 2 and len(spans[0]) == 1:
            char, source = spans
            return SolverResult(answer=str(source.count(char)), confident=True)
        return SolverResult(answer=None, confident=False)

    target = _extract_target(prompt)
    if target is None:
        return SolverResult(answer=None, confident=False)

    if _REVERSE_WORD_ORDER_RE.search(prompt):
        return SolverResult(answer=" ".join(reversed(target.split())), confident=True)

    if _REVERSE_RE.search(prompt):
        return SolverResult(answer=target[::-1], confident=True)

    if _UPPER_RE.search(prompt):
        return SolverResult(answer=target.upper(), confident=True)

    if _LOWER_RE.search(prompt):
        return SolverResult(answer=target.lower(), confident=True)

    first_n_match = _FIRST_N_RE.search(prompt)
    if first_n_match:
        n = int(first_n_match.group("n"))
        return SolverResult(answer=target[:n], confident=True)

    last_n_match = _LAST_N_RE.search(prompt)
    if last_n_match:
        n = int(last_n_match.group("n"))
        return SolverResult(answer=target[-n:] if n > 0 else "", confident=True)

    if _COUNT_WORD_RE.search(prompt):
        word_count = len(target.split())
        return SolverResult(answer=str(word_count), confident=True)

    if _LENGTH_RE.search(prompt):
        return SolverResult(answer=str(len(target)), confident=True)

    if _SORT_RE.search(prompt):
        return SolverResult(answer="".join(sorted(target)), confident=True)

    return SolverResult(answer=None, confident=False)
