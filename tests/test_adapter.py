"""Adapter roundtrip tests: synthetic tasks.json -> results.json, using only
Tier-0-resolvable tasks so no network call is made. Also covers CLI arg
parsing and tolerant schema handling.
"""

from __future__ import annotations

import json

import pytest

from routing_agent.adapter import _parse_tasks, _read_tasks, main, parse_args, run
from routing_agent.config import Settings


def test_parse_args_defaults_to_none():
    args = parse_args([])
    assert args.input is None
    assert args.output is None
    assert args.policy is None


def test_parse_args_accepts_explicit_paths():
    args = parse_args(["--input", "in.json", "--output", "out.json"])
    assert args.input == "in.json"
    assert args.output == "out.json"


def test_read_tasks_from_explicit_file(tmp_path):
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps([{"id": "1", "prompt": "2+2"}]), encoding="utf-8")
    result = _read_tasks(str(tasks_file), stdin=None)
    assert result == [{"id": "1", "prompt": "2+2"}]


def test_read_tasks_rejects_non_list_payload(tmp_path):
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps({"id": "1"}), encoding="utf-8")
    with pytest.raises(ValueError, match="top-level JSON array"):
        _read_tasks(str(tasks_file), stdin=None)


def test_parse_tasks_tolerates_alias_field_names():
    raw = [
        {"id": "1", "prompt": "2+2"},
        {"id": "2", "input": "3+3"},
        {"question": "4+4"},  # missing id -> assigned by index
    ]
    tasks = _parse_tasks(raw)
    assert [t.id for t in tasks] == ["1", "2", "2"]
    assert tasks[2].prompt == "4+4"


def test_run_resolves_tier0_tasks_without_network():
    raw = [
        {"id": "a", "prompt": "2 + 2"},
        {"id": "b", "prompt": "What is 17% of 340?"},
        {"id": "c", "prompt": "What day of the week is July 4, 2026?"},
    ]
    tasks = _parse_tasks(raw)
    settings = Settings.from_env({"FIREWORKS_API_KEY": "fw_test", "ALLOWED_MODELS": ""})

    results, summary = run(tasks, settings, policy_path=None)

    assert {r["id"]: r["output"] for r in results} == {
        "a": "4",
        "b": "57.8",
        "c": "Saturday",
    }
    assert summary["total_tasks"] == 3
    assert summary["tier_distribution"] == {0: 3}
    assert summary["total_raw_tokens"] == 0
    assert summary["total_calls"] == 0
    # results payload must only ever contain id/output keys.
    for result in results:
        assert set(result.keys()) == {"id", "output"}


def test_run_falls_back_gracefully_with_no_allowed_models_and_no_tier0_match():
    raw = [{"id": "z", "prompt": "Tell me an interesting fact."}]
    tasks = _parse_tasks(raw)
    settings = Settings.from_env({"FIREWORKS_API_KEY": "fw_test", "ALLOWED_MODELS": ""})

    results, summary = run(tasks, settings, policy_path=None)

    assert results == [{"id": "z", "output": ""}]
    assert summary["total_calls"] == 0


def test_main_end_to_end_roundtrip(tmp_path, monkeypatch):
    input_path = tmp_path / "tasks.json"
    output_path = tmp_path / "results.json"
    input_path.write_text(
        json.dumps([{"id": "1", "prompt": "2 + 2"}, {"id": "2", "prompt": "10 // 3"}]),
        encoding="utf-8",
    )
    monkeypatch.setenv("FIREWORKS_API_KEY", "fw_test")
    monkeypatch.setenv("ALLOWED_MODELS", "")

    exit_code = main(["--input", str(input_path), "--output", str(output_path)])

    assert exit_code == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written == [{"id": "1", "output": "4"}, {"id": "2", "output": "3"}]


def test_main_fails_gracefully_without_api_key(tmp_path, monkeypatch):
    input_path = tmp_path / "tasks.json"
    input_path.write_text(json.dumps([{"id": "1", "prompt": "2 + 2"}]), encoding="utf-8")
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)

    exit_code = main(["--input", str(input_path)])

    assert exit_code == 1
