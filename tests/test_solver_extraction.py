"""Tests for the regex-based extraction Tier-0 solver."""

from __future__ import annotations

from routing_agent.classifier import TaskType
from routing_agent.models import Task
from routing_agent.solvers import extraction


def _task(prompt: str) -> Task:
    return Task(id="t1", prompt=prompt)


def test_extracts_single_email():
    result = extraction.try_solve(
        _task("Extract the email from: Contact us at hello@example.com for help."),
        TaskType.EXTRACTION,
    )
    assert result.confident is True
    assert result.answer == "hello@example.com"


def test_extracts_single_url():
    result = extraction.try_solve(
        _task("Find the url in: Visit https://example.com/page for details."),
        TaskType.EXTRACTION,
    )
    assert result.confident is True
    assert result.answer == "https://example.com/page"


def test_extracts_all_emails_when_plural_ask():
    result = extraction.try_solve(
        _task("List all emails in: reach a@x.com or b@y.com for support."),
        TaskType.EXTRACTION,
    )
    assert result.confident is True
    assert result.answer == "a@x.com, b@y.com"


def test_extracts_phone_number():
    result = extraction.try_solve(
        _task("Find the phone number in: Call us at 555-123-4567 today."),
        TaskType.EXTRACTION,
    )
    assert result.confident is True
    assert result.answer == "555-123-4567"


def test_extracts_iso_date():
    result = extraction.try_solve(
        _task("Find the date in: The event is on 2026-07-11 at noon."),
        TaskType.EXTRACTION,
    )
    assert result.confident is True
    assert result.answer == "2026-07-11"


def test_returns_not_confident_when_no_match_found():
    result = extraction.try_solve(
        _task("Extract the email from: no contact info here."),
        TaskType.EXTRACTION,
    )
    assert result.confident is False
    assert result.answer is None


def test_returns_not_confident_on_multiple_categories_requested():
    # Adversarial: asks for two categories at once, which is ambiguous for
    # this single-category solver.
    result = extraction.try_solve(
        _task("Extract the email and phone number from: hello@example.com, 555-123-4567"),
        TaskType.EXTRACTION,
    )
    assert result.confident is False


def test_returns_not_confident_on_wrong_task_type():
    result = extraction.try_solve(
        _task("Extract the email from: hello@example.com"), TaskType.GENERAL
    )
    assert result.confident is False


def test_extracts_comma_grouped_number_as_single_value():
    # Regression: the number regex previously split "1,250,000" into three
    # separate matches (found via eval audit, extraction-011).
    result = extraction.try_solve(
        _task(
            'Extract the number from this text: "Total revenue for the quarter '
            'reached 1,250,000 dollars."'
        ),
        TaskType.EXTRACTION,
    )
    assert result.confident is True
    assert result.answer == "1,250,000"


def test_extracts_url_without_trailing_sentence_period():
    # Regression: the URL regex previously swallowed a sentence-ending "."
    # right after the URL (found via eval audit, extraction-017).
    result = extraction.try_solve(
        _task(
            'Extract the URL from this text: "The API reference can be found '
            'at https://api.dataservice.com/v2/docs."'
        ),
        TaskType.EXTRACTION,
    )
    assert result.confident is True
    assert result.answer == "https://api.dataservice.com/v2/docs"
