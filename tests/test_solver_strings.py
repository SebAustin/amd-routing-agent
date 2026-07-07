"""Tests for the string-operation Tier-0 solver."""

from __future__ import annotations

from routing_agent.classifier import TaskType
from routing_agent.models import Task
from routing_agent.solvers import strings


def _task(prompt: str) -> Task:
    return Task(id="t1", prompt=prompt)


def test_solves_reverse():
    result = strings.try_solve(_task('Reverse the string "hello"'), TaskType.STRING_OP)
    assert result.confident is True
    assert result.answer == "olleh"


def test_solves_uppercase():
    result = strings.try_solve(_task('Uppercase the string "hello"'), TaskType.STRING_OP)
    assert result.answer == "HELLO"


def test_solves_lowercase():
    result = strings.try_solve(_task('Lowercase the string "HELLO"'), TaskType.STRING_OP)
    assert result.answer == "hello"


def test_solves_length():
    result = strings.try_solve(
        _task('How many characters are in "hello world"?'), TaskType.STRING_OP
    )
    assert result.confident is True
    assert result.answer == "11"


def test_solves_count_char_occurrences():
    result = strings.try_solve(
        _task('How many times does "l" occur in "hello"?'), TaskType.STRING_OP
    )
    assert result.confident is True
    assert result.answer == "2"


def test_solves_count_words():
    result = strings.try_solve(
        _task('How many words in "the quick brown fox"?'), TaskType.STRING_OP
    )
    assert result.answer == "4"


def test_solves_first_n_chars():
    result = strings.try_solve(
        _task('Give the first 3 characters of "hello world"'), TaskType.STRING_OP
    )
    assert result.answer == "hel"


def test_solves_last_n_chars():
    result = strings.try_solve(
        _task('Give the last 3 characters of "hello world"'), TaskType.STRING_OP
    )
    assert result.answer == "rld"


def test_solves_sort_letters():
    result = strings.try_solve(_task('Sort the letters of "dcba"'), TaskType.STRING_OP)
    assert result.answer == "abcd"


def test_returns_not_confident_without_quoted_target():
    # Adversarial: no quotes -> ambiguous which words are the operand.
    result = strings.try_solve(_task("Reverse the word hello"), TaskType.STRING_OP)
    assert result.confident is False
    assert result.answer is None


def test_returns_not_confident_on_unsupported_operation():
    result = strings.try_solve(_task('Capitalize each word in "hello world"'), TaskType.STRING_OP)
    assert result.confident is False


def test_returns_not_confident_on_wrong_task_type():
    result = strings.try_solve(_task('Reverse "hello"'), TaskType.GENERAL)
    assert result.confident is False
