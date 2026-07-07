"""Tests for Task's tolerant alias parsing (prompt/input/question/text)."""

from __future__ import annotations

from routing_agent.models import CallRecord, Task


def test_task_accepts_prompt_field():
    task = Task.model_validate({"id": "1", "prompt": "hi"})
    assert task.prompt == "hi"


def test_task_accepts_input_alias():
    task = Task.model_validate({"id": "1", "input": "hi"})
    assert task.prompt == "hi"


def test_task_accepts_question_alias():
    task = Task.model_validate({"id": "1", "question": "hi"})
    assert task.prompt == "hi"


def test_task_accepts_text_alias():
    task = Task.model_validate({"id": "1", "text": "hi"})
    assert task.prompt == "hi"


def test_task_prefers_prompt_over_other_aliases():
    task = Task.model_validate({"id": "1", "prompt": "real", "input": "ignored"})
    assert task.prompt == "real"


def test_task_default_type_and_metadata():
    task = Task.model_validate({"id": "1", "prompt": "hi"})
    assert task.type is None
    assert task.metadata == {}


def test_call_record_total_tokens():
    record = CallRecord(model="m", prompt_tokens=10, completion_tokens=5)
    assert record.total_tokens == 15
