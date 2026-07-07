"""Classifier routing table tests: each prompt should land on the expected
TaskType, with a conservative GENERAL fallback for ambiguous input.
"""

from __future__ import annotations

import pytest

from routing_agent.classifier import TaskType, classify

_ROUTING_TABLE: list[tuple[str, TaskType]] = [
    ("2 + 2", TaskType.ARITHMETIC),
    ("What is 17% of 340?", TaskType.ARITHMETIC),
    ("What is the sum of 4 and 9?", TaskType.ARITHMETIC),
    ("What date is 45 days after March 3, 2026?", TaskType.DATE_MATH),
    ("What day of the week is July 4, 2026?", TaskType.DATE_MATH),
    ("How many days between January 1 and January 31, 2026?", TaskType.DATE_MATH),
    ('Reverse the string "hello"', TaskType.STRING_OP),
    ('How many characters are in "hello world"?', TaskType.STRING_OP),
    ("Convert 10 km to miles", TaskType.UNIT_CONVERSION),
    ("Convert 100 celsius to fahrenheit", TaskType.UNIT_CONVERSION),
    ("Extract the email from: hello@example.com", TaskType.EXTRACTION),
    ("Find the url in this text", TaskType.EXTRACTION),
    ("Classify the sentiment of this review as positive or negative", TaskType.CLASSIFICATION),
    ("Is this email spam or ham?", TaskType.CLASSIFICATION),
    ("Which of the following is a mammal? (a) Shark (b) Dolphin", TaskType.MULTIPLE_CHOICE),
    ("Write a function in python that reverses a list", TaskType.CODE),
    ("Fix the bug in this code snippet", TaskType.CODE),
    ("Summarize the following article in one paragraph", TaskType.SUMMARIZATION),
    ("Who was the first president of the United States?", TaskType.SHORT_QA),
    ("What is the capital of France?", TaskType.SHORT_QA),
    ("Tell me a story about a dragon.", TaskType.GENERAL),
    ("", TaskType.GENERAL),
]


@pytest.mark.parametrize("prompt,expected_type", _ROUTING_TABLE)
def test_classify_routing_table(prompt: str, expected_type: TaskType):
    assert classify(prompt) == expected_type


def test_classify_falls_back_to_general_on_ambiguous_prompt():
    assert classify("asdkjfh aslkdjf laksjdf") == TaskType.GENERAL


def test_classify_is_whitespace_tolerant():
    assert classify("   2 + 2   ") == TaskType.ARITHMETIC


# Regression cases found while tuning against evals/evalset (200-task audit):
# each of these was misclassified before the corresponding regex fix.
_REGRESSION_TABLE: list[tuple[str, TaskType]] = [
    # Inline "A) ... B) ..." options (no line anchor) previously fell to SHORT_QA.
    (
        "What is the capital of France? A) Berlin B) Madrid C) Paris D) Rome",
        TaskType.MULTIPLE_CHOICE,
    ),
    (
        "In which year did World War II end? A) 1943 B) 1944 C) 1945 D) 1946",
        TaskType.MULTIPLE_CHOICE,
    ),
    # "What does this Python code print?" fell to SHORT_QA/ARITHMETIC.
    ("What does this Python code print?\n\nprint(3 + 4 * 2)", TaskType.CODE),
    (
        "What does this Python code print?\n\nd = {'a': 1, 'b': 2}\nd['c'] = 3\nprint(len(d))",
        TaskType.CODE,
    ),
    # Word-problem arithmetic phrasing fell to GENERAL (the trailing \b after
    # a digit-ending alternative like "add \d" never matched).
    ("Add 12345 and 6789.", TaskType.ARITHMETIC),
    ("Subtract 4321 from 9876.", TaskType.ARITHMETIC),
    ("Compute 17 * 23.", TaskType.ARITHMETIC),
    ("Multiply 37 by 19.", TaskType.ARITHMETIC),
    ("What is 56 squared?", TaskType.ARITHMETIC),
    ("A shirt priced at $250 is marked up by 20%. What is the new price?", TaskType.ARITHMETIC),
    (
        "A $500 bill has a 6% tax added. What is the total, rounded to 2 decimal places?",
        TaskType.ARITHMETIC,
    ),
    # "times" inside "How many times does X appear" is not multiplication.
    ('How many times does the letter "s" appear in "mississippi"?', TaskType.STRING_OP),
    # "tax" as a substring of "tax incentives" inside prose is not arithmetic.
    (
        'Summarize the following text in one sentence. Text: "Electric vehicles are '
        "becoming more common. Many governments now offer tax incentives to encourage "
        'adoption."',
        TaskType.SUMMARIZATION,
    ),
    # Language identification is a classification task, not GENERAL.
    (
        "Identify the language of this sentence as one of: English, Spanish, French, "
        'German. Sentence: "Bonjour, comment allez-vous?"',
        TaskType.CLASSIFICATION,
    ),
    # Character-position / palindrome / title-case string ops fell to
    # SHORT_QA/GENERAL/ARITHMETIC.
    ('What is the 3rd character of the word "benchmark"?', TaskType.STRING_OP),
    ('Convert "the great gatsby" to title case.', TaskType.STRING_OP),
    ('Is the word "racecar" a palindrome? Answer yes or no.', TaskType.STRING_OP),
    # "How many MB are in 1 GB" phrasing (no leading "convert") fell to GENERAL.
    ("Using 1 GB = 1024 MB, how many MB are in 1 GB?", TaskType.UNIT_CONVERSION),
    # "days between/from" and leap-year phrasing fell to SHORT_QA/GENERAL.
    (
        "How many days are there between January 1, 2025 and March 1, 2025?",
        TaskType.DATE_MATH,
    ),
    ("How many days are there from June 15, 2025 to September 1, 2025?", TaskType.DATE_MATH),
    ("Is the year 2028 a leap year? Answer yes or no.", TaskType.DATE_MATH),
    ("How many days are in February 2028?", TaskType.DATE_MATH),
]


@pytest.mark.parametrize("prompt,expected_type", _REGRESSION_TABLE)
def test_classify_regression_table(prompt: str, expected_type: TaskType):
    assert classify(prompt) == expected_type
