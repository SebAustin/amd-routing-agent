"""Zero-token task classification via ordered regex/heuristic rules.

Purely local; never calls a model. Conservative by design: when no rule
confidently matches, the task falls back to `TaskType.GENERAL` rather than
guessing, since Tier-0/Tier-1 routing decisions downstream key off this type.
"""

from __future__ import annotations

import re
from enum import StrEnum


class TaskType(StrEnum):
    ARITHMETIC = "arithmetic"
    DATE_MATH = "date_math"
    STRING_OP = "string_op"
    UNIT_CONVERSION = "unit_conversion"
    EXTRACTION = "extraction"
    CLASSIFICATION = "classification"
    MULTIPLE_CHOICE = "multiple_choice"
    SHORT_QA = "short_qa"
    CODE = "code"
    SUMMARIZATION = "summarization"
    GENERAL = "general"


_ARITHMETIC_EXPR_RE = re.compile(r"^[\s0-9+\-*/%().^]+$")
_ARITHMETIC_WORDED_RE = re.compile(
    r"\b(sum of|product of|difference|quotient|square root|percent\b|percentage|"
    r"multiplied by|divided by|\bplus\b|\bminus\b|\d+ times\b|"
    r"add \d|subtract \d|compute \d|multiply \d|"
    r"squared|cubed|raised to the power|to the power of|"
    r"marked up|discounted|\d+% tax|has a \d+% tax|markup|"
    r"how much (do you have|does it cost)|total cost|"
    r"how many .* (are needed|do you need)|"
    r"rounded to \d+ decimal places?)",
    re.IGNORECASE,
)
_ARITHMETIC_KEYWORD_RE = re.compile(r"what\s+is\s+[\d.\s+\-*/%()]+[+\-*/%]", re.IGNORECASE)
_PERCENT_OF_RE = re.compile(r"\d+(\.\d+)?\s*%\s*of\s+\d+(\.\d+)?", re.IGNORECASE)

_DATE_MATH_RE = re.compile(
    r"\b(days? (after|before|from)|weekday of|day of the week|"
    r"how many days (are there|between|until|since|from)|"
    r"is (the year|\d{4}) .*leap year|leap year|"
    r"how many days (are )?in\b|date (is|was))\b",
    re.IGNORECASE,
)
_DATE_TOKEN_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b",
    re.IGNORECASE,
)

_STRING_OP_RE = re.compile(
    r"\b(reverse|uppercase|lowercase|upper[- ]?case|lower[- ]?case|title case|"
    r"how many (letters|characters|vowels|words)|count the (occurrences|letters)|"
    r"how many times does the letter|"
    r"first \d+ characters|last \d+ characters|sort the letters|"
    r"(\d+(st|nd|rd|th)|first|last) character of|palindrome)\b",
    re.IGNORECASE,
)

_UNIT_CONVERSION_RE = re.compile(
    r"(\bconvert\b.*\b(km|kilometers?|miles?|meters?|feet|ft|inches?|cm|"
    r"celsius|fahrenheit|kelvin|kg|kilograms?|pounds?|lbs?|grams?|"
    r"kb|mb|gb|tb|bytes?)\b|"
    r"how many (mb|kb|gb|tb|bytes?|meters?|feet|inches?|km|miles?|kg|grams?|pounds?) "
    r"(are|is) (in|there in))",
    re.IGNORECASE,
)

_EXTRACTION_RE = re.compile(
    r"\b(extract|find the (email|url|phone|number|date)s?|"
    r"list all (email|url|phone|number|date)s?)\b",
    re.IGNORECASE,
)

_MULTIPLE_CHOICE_PAREN_RE = re.compile(r"\([a-dA-D]\)", re.MULTILINE)
_MULTIPLE_CHOICE_LINE_RE = re.compile(r"^[a-dA-D][).]\s", re.MULTILINE)
# Inline "A) foo B) bar" option markers (no line anchor needed) — requires at
# least two to avoid false positives on prose containing a single "B)".
_MULTIPLE_CHOICE_INLINE_RE = re.compile(r"\b[A-D]\)\s*\S")
_MULTIPLE_CHOICE_HINT_RE = re.compile(
    r"\bchoose the correct\b|\bselect one\b|\bwhich of the following\b", re.IGNORECASE
)

_CLASSIFICATION_RE = re.compile(
    r"\b(classify|categorize|label|identify the language|"
    r"is (this|the following)\b.{0,20}\b(positive|negative|spam|ham)|sentiment)\b",
    re.IGNORECASE,
)

_CODE_RE = re.compile(
    r"\b(write a function|write code|implement|def |function\s*\(|"
    r"in (python|javascript|java|c\+\+|go|rust)\b|fix the bug|debug this|"
    r"what does this (code|python|javascript|java)?\s*(code )?(print|output|return)|"
    r"what (is|will be) the output of|what does this snippet)\b",
    re.IGNORECASE,
)

_SUMMARIZATION_RE = re.compile(
    r"\b(summarize|summary of|tl;?dr|in (one|a few) sentences?, summarize)\b",
    re.IGNORECASE,
)

_SHORT_QA_HINT_RE = re.compile(r"^(who|what|when|where|which|how many|how much)\b", re.IGNORECASE)


def classify(prompt: str) -> TaskType:
    """Classify a task prompt into a `TaskType` using ordered heuristics.

    Rules are checked most-specific-first so that, e.g., a date-math question
    phrased as a "what" question is caught by DATE_MATH before falling
    through to the generic SHORT_QA bucket. Returns GENERAL when no rule
    matches confidently.
    """
    text = prompt.strip()
    if not text:
        return TaskType.GENERAL

    stripped_expr = text.rstrip("? .")
    if _ARITHMETIC_EXPR_RE.match(stripped_expr) and any(c.isdigit() for c in text):
        return TaskType.ARITHMETIC
    if _PERCENT_OF_RE.search(text):
        return TaskType.ARITHMETIC
    if _ARITHMETIC_KEYWORD_RE.search(text) or _ARITHMETIC_WORDED_RE.search(text):
        return TaskType.ARITHMETIC

    if _DATE_MATH_RE.search(text) and _DATE_TOKEN_RE.search(text):
        return TaskType.DATE_MATH
    if _DATE_MATH_RE.search(text):
        return TaskType.DATE_MATH

    if _UNIT_CONVERSION_RE.search(text):
        return TaskType.UNIT_CONVERSION

    if _STRING_OP_RE.search(text):
        return TaskType.STRING_OP

    if _EXTRACTION_RE.search(text):
        return TaskType.EXTRACTION

    if _CODE_RE.search(text):
        return TaskType.CODE

    if _SUMMARIZATION_RE.search(text):
        return TaskType.SUMMARIZATION

    if (
        _MULTIPLE_CHOICE_PAREN_RE.search(text)
        or _MULTIPLE_CHOICE_LINE_RE.search(text)
        or len(_MULTIPLE_CHOICE_INLINE_RE.findall(text)) >= 2
        or _MULTIPLE_CHOICE_HINT_RE.search(text)
    ):
        return TaskType.MULTIPLE_CHOICE

    if _CLASSIFICATION_RE.search(text):
        return TaskType.CLASSIFICATION

    if _SHORT_QA_HINT_RE.match(text) and len(text) < 200:
        return TaskType.SHORT_QA

    return TaskType.GENERAL
