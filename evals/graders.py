"""Grading utilities for the routing-agent evaluation dataset.

Stdlib-only. Provides:
- ``grade(expected, actual, grader, grader_args) -> bool``: dispatches to one
  of five grading strategies (exact, normalized, numeric, contains_all,
  choice).
- ``iter_evalset(dir) -> Iterator[dict]``: loads and validates every JSONL
  task file in a directory, enforcing the required schema and unique ids.

Run as a script (``python3 evals/graders.py``) to self-check the evalset:
every task is loaded, schema-validated, and graded against itself
(identity check, expected == actual) which must always pass. Prints
per-category counts and exits non-zero on any failure.
"""

from __future__ import annotations

import json
import re
import string
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REQUIRED_KEYS = {"id", "category", "prompt", "expected", "grader"}
VALID_GRADERS = {"exact", "normalized", "numeric", "contains_all", "choice"}

# Small set of English articles stripped during normalization. Kept narrow
# and explicit rather than pulling in a stopword list, so normalization stays
# predictable for short factual answers (capitals, chemical symbols, etc.).
_ARTICLES = {"a", "an", "the"}

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")
_CHOICE_RE = re.compile(r"\b([A-D])\b")

_DEFAULT_REL_TOLERANCE = 1e-6


def _strip_punctuation(text: str) -> str:
    """Remove punctuation characters, collapsing them to nothing."""
    return text.translate(str.maketrans("", "", string.punctuation))


def _strip_diacritics(text: str) -> str:
    """Fold accented characters to their ASCII base (e.g. 'Brasília' -> 'Brasilia')."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    """Casefold, strip diacritics/punctuation/articles, and collapse whitespace.

    Used by the ``normalized`` grader for free-text answers where casing,
    accents, trailing punctuation, or a leading article should not affect
    correctness (e.g. "The Amazon River" == "amazon river", "Brasília" ==
    "Brasilia").
    """
    lowered = text.casefold().strip()
    no_accents = _strip_diacritics(lowered)
    no_punct = _strip_punctuation(no_accents)
    tokens = [tok for tok in no_punct.split() if tok not in _ARTICLES]
    return " ".join(tokens)


def _parse_first_number(text: str) -> float:
    """Extract the first numeric value from ``text``.

    Handles thousands separators (commas), a trailing percent sign, and a
    leading currency symbol. Raises ``ValueError`` if no number is found.
    """
    cleaned = text.replace("$", "").replace("%", "")
    match = _NUMBER_RE.search(cleaned)
    if match is None:
        raise ValueError(f"no numeric value found in {text!r}")
    return float(match.group().replace(",", ""))


def grade_exact(expected: str, actual: str) -> bool:
    """Exact match after stripping leading/trailing whitespace only."""
    return expected.strip() == actual.strip()


def grade_normalized(expected: str, actual: str) -> bool:
    """Match after casefolding, punctuation/article stripping, whitespace collapse."""
    return normalize_text(expected) == normalize_text(actual)


def grade_numeric(expected: str, actual: str, grader_args: dict[str, Any] | None = None) -> bool:
    """Match the first number parsed from each string within a tolerance.

    ``grader_args`` may supply ``tolerance`` (treated as absolute tolerance)
    or an explicit ``abs_tolerance`` / ``rel_tolerance`` pair. Default is a
    relative tolerance of 1e-6 with a small absolute floor, so exact integer
    and float comparisons behave intuitively.
    """
    grader_args = grader_args or {}
    try:
        expected_value = _parse_first_number(str(expected))
        actual_value = _parse_first_number(str(actual))
    except ValueError:
        return False

    if "tolerance" in grader_args:
        abs_tolerance = float(grader_args["tolerance"])
        rel_tolerance = 0.0
    else:
        abs_tolerance = float(grader_args.get("abs_tolerance", 1e-9))
        rel_tolerance = float(grader_args.get("rel_tolerance", _DEFAULT_REL_TOLERANCE))

    allowed_diff = max(abs_tolerance, rel_tolerance * abs(expected_value))
    return abs(expected_value - actual_value) <= allowed_diff


def grade_contains_all(actual: str, grader_args: dict[str, Any] | None = None) -> bool:
    """True if every keyword in ``grader_args['keywords']`` appears in ``actual``.

    Case-insensitive substring containment; keywords act as stems (e.g.
    "declin" matches "declining"), so short fragments are valid keywords.
    """
    grader_args = grader_args or {}
    keywords = grader_args.get("keywords", [])
    if not keywords:
        return False
    lowered_actual = actual.casefold()
    return all(keyword.casefold() in lowered_actual for keyword in keywords)


def grade_choice(expected: str, actual: str) -> bool:
    """Extract an A-D answer letter from messy output and compare.

    Handles bare letters ("B"), trailing punctuation ("B."), parentheses
    ("(B)"), and phrases ("The answer is B").
    """
    expected_letter = expected.strip().strip("().").upper()
    match = _CHOICE_RE.search(actual.upper())
    if match is None:
        return False
    return match.group(1) == expected_letter


def grade(
    expected: str, actual: str, grader: str, grader_args: dict[str, Any] | None = None
) -> bool:
    """Dispatch to the grading strategy named by ``grader``.

    Args:
        expected: The reference answer.
        actual: The candidate answer to score.
        grader: One of "exact", "normalized", "numeric", "contains_all", "choice".
        grader_args: Optional per-task grading parameters (tolerance, keywords, choices).

    Returns:
        True if ``actual`` is graded correct against ``expected``.

    Raises:
        ValueError: If ``grader`` is not a recognized grading strategy.
    """
    grader_args = grader_args or {}
    if grader == "exact":
        return grade_exact(expected, actual)
    if grader == "normalized":
        return grade_normalized(expected, actual)
    if grader == "numeric":
        return grade_numeric(expected, actual, grader_args)
    if grader == "contains_all":
        return grade_contains_all(actual, grader_args)
    if grader == "choice":
        return grade_choice(expected, actual)
    raise ValueError(f"unknown grader: {grader!r}")


def _validate_task(task: dict[str, Any], source: Path) -> None:
    """Raise ``ValueError`` if ``task`` is missing required keys or has an invalid grader."""
    missing = REQUIRED_KEYS - task.keys()
    if missing:
        raise ValueError(f"{source}: task {task.get('id', '?')!r} missing keys {missing}")
    if task["grader"] not in VALID_GRADERS:
        raise ValueError(f"{source}: task {task['id']!r} has unknown grader {task['grader']!r}")
    if task["grader"] == "contains_all":
        keywords = task.get("grader_args", {}).get("keywords")
        if not keywords:
            raise ValueError(f"{source}: task {task['id']!r} uses contains_all but has no keywords")


def iter_evalset(directory: str | Path) -> Iterator[dict[str, Any]]:
    """Yield every task dict from the JSONL files in ``directory``.

    Validates required keys, known grader names, and globally unique ids
    across all files. Raises ``ValueError`` on any schema violation or
    duplicate id.
    """
    directory = Path(directory)
    seen_ids: set[str] = set()
    for jsonl_path in sorted(directory.glob("*.jsonl")):
        with jsonl_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    task = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{jsonl_path}:{line_number}: invalid JSON ({exc})") from exc
                _validate_task(task, jsonl_path)
                if task["id"] in seen_ids:
                    raise ValueError(f"{jsonl_path}: duplicate id {task['id']!r}")
                seen_ids.add(task["id"])
                yield task


def _self_check(directory: Path) -> int:
    """Load every task, validate schema, and run the identity grading check.

    Returns the process exit code (0 on success, 1 on any failure).
    """
    category_counts: Counter[str] = Counter()
    failures: list[str] = []
    total = 0

    try:
        tasks = list(iter_evalset(directory))
    except ValueError as exc:
        print(f"FAIL: schema validation error: {exc}")
        return 1

    for task in tasks:
        total += 1
        category_counts[task["category"]] += 1
        grader_args = task.get("grader_args", {})
        try:
            passed = grade(task["expected"], task["expected"], task["grader"], grader_args)
        except ValueError as exc:
            failures.append(f"{task['id']}: grader raised {exc}")
            continue
        if not passed:
            failures.append(f"{task['id']}: identity check failed (grader={task['grader']!r})")

    print("Evalset self-check")
    print("===================")
    for category in sorted(category_counts):
        print(f"  {category:<16} {category_counts[category]:>4}")
    print(f"  {'TOTAL':<16} {total:>4}")
    print()

    if failures:
        print(f"FAIL: {len(failures)} identity check failure(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"PASS: all {total} tasks loaded, schema-valid, and pass identity grading.")
    return 0


if __name__ == "__main__":
    evalset_dir = Path(__file__).parent / "evalset"
    sys.exit(_self_check(evalset_dir))
