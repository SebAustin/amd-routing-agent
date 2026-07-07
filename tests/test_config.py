"""Config parsing tests: ALLOWED_MODELS variants, Settings.from_env, and
policy YAML loading.
"""

from __future__ import annotations

import pytest

from routing_agent.config import (
    DEFAULT_FIREWORKS_BASE_URL,
    Policy,
    Settings,
    load_policy,
    parse_allowed_models,
)


def test_parse_allowed_models_comma_separated_bare_names():
    result = parse_allowed_models("gpt-oss-20b, deepseek-v4-flash")
    assert result == [
        "accounts/fireworks/models/gpt-oss-20b",
        "accounts/fireworks/models/deepseek-v4-flash",
    ]


def test_parse_allowed_models_already_prefixed():
    result = parse_allowed_models("accounts/fireworks/models/gpt-oss-20b")
    assert result == ["accounts/fireworks/models/gpt-oss-20b"]


def test_parse_allowed_models_mixed_prefix_and_bare():
    result = parse_allowed_models("accounts/fireworks/models/gpt-oss-20b,glm-5p1")
    assert result == [
        "accounts/fireworks/models/gpt-oss-20b",
        "accounts/fireworks/models/glm-5p1",
    ]


def test_parse_allowed_models_json_array():
    result = parse_allowed_models('["gpt-oss-20b", "glm-5p1"]')
    assert result == [
        "accounts/fireworks/models/gpt-oss-20b",
        "accounts/fireworks/models/glm-5p1",
    ]


def test_parse_allowed_models_deduplicates_preserving_order():
    result = parse_allowed_models("gpt-oss-20b,gpt-oss-20b,glm-5p1")
    assert result == [
        "accounts/fireworks/models/gpt-oss-20b",
        "accounts/fireworks/models/glm-5p1",
    ]


def test_parse_allowed_models_empty_and_none():
    assert parse_allowed_models(None) == []
    assert parse_allowed_models("") == []
    assert parse_allowed_models("   ") == []


def test_parse_allowed_models_skips_blank_entries():
    result = parse_allowed_models("gpt-oss-20b,,  ,glm-5p1")
    assert result == [
        "accounts/fireworks/models/gpt-oss-20b",
        "accounts/fireworks/models/glm-5p1",
    ]


def test_parse_allowed_models_rejects_non_string_json_array():
    with pytest.raises(ValueError, match="must contain only strings"):
        parse_allowed_models("[1, 2, 3]")


def test_settings_from_env_requires_api_key():
    with pytest.raises(ValueError, match="FIREWORKS_API_KEY"):
        Settings.from_env({})


def test_settings_from_env_uses_default_base_url_when_absent():
    settings = Settings.from_env({"FIREWORKS_API_KEY": "fw_test123"})
    assert settings.fireworks_base_url == DEFAULT_FIREWORKS_BASE_URL
    assert settings.allowed_models == []


def test_settings_from_env_parses_allowed_models():
    settings = Settings.from_env(
        {
            "FIREWORKS_API_KEY": "fw_test123",
            "ALLOWED_MODELS": "gpt-oss-20b,glm-5p1",
        }
    )
    assert settings.allowed_models == [
        "accounts/fireworks/models/gpt-oss-20b",
        "accounts/fireworks/models/glm-5p1",
    ]


def test_settings_from_env_strips_trailing_slash_from_base_url():
    settings = Settings.from_env(
        {
            "FIREWORKS_API_KEY": "fw_test123",
            "FIREWORKS_BASE_URL": "https://example.com/v1/",
        }
    )
    assert settings.fireworks_base_url == "https://example.com/v1"


def test_load_policy_returns_defaults_when_path_is_none():
    policy = load_policy(None)
    assert isinstance(policy, Policy)
    assert policy.objective == "raw_tokens"
    assert policy.retry_budget == 1


def test_load_policy_returns_defaults_when_file_missing(tmp_path):
    policy = load_policy(tmp_path / "does_not_exist.yaml")
    assert policy.objective == "raw_tokens"


def test_load_policy_reads_yaml_overrides(tmp_path):
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(
        "confidence_threshold: 0.8\nretry_budget: 2\nobjective: price_weighted\n"
        "max_tokens:\n  classification: 4\n",
        encoding="utf-8",
    )
    policy = load_policy(policy_file)
    assert policy.confidence_threshold == 0.8
    assert policy.retry_budget == 2
    assert policy.objective == "price_weighted"
    assert policy.max_tokens_for("classification") == 4


def test_policy_max_tokens_for_falls_back_to_general():
    policy = Policy()
    assert policy.max_tokens_for("nonexistent_type") == policy.max_tokens["general"]
