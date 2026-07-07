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
