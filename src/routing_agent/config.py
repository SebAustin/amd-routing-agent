"""Environment settings and YAML routing-policy loading.

`Settings` reads Fireworks credentials and the `ALLOWED_MODELS` allowlist from
the environment. `ALLOWED_MODELS` is parsed tolerantly: comma-separated ids,
a JSON array, or bare model names with/without the
`accounts/fireworks/models/` prefix — all normalized to full ids.

`Policy` is the routing-tunable knob set (confidence thresholds, per-task-type
max_tokens, retry budget, scoring objective), loaded from a YAML file under
`evals/policies/`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from routing_agent.registry import FIREWORKS_MODEL_PREFIX

DEFAULT_FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"

# Per-task-type default max_tokens (PLAN.md §3 / prompts.py contract).
DEFAULT_MAX_TOKENS: dict[str, int] = {
    "classification": 8,
    "multiple_choice": 8,
    "extraction": 24,
    "short_qa": 32,
    "code": 256,
    "summarization": 160,
    "general": 96,
    "arithmetic": 32,
    "date_math": 32,
    "string_op": 32,
    "unit_conversion": 32,
}

Objective = Literal["raw_tokens", "price_weighted"]


class Policy(BaseModel):
    """Routing-tunable policy, loaded from YAML (evals/policies/*.yaml)."""

    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    logprob_threshold: float = Field(default=-1.0)
    max_tokens: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_MAX_TOKENS))
    retry_budget: int = Field(default=1, ge=0)
    objective: Objective = "raw_tokens"

    def max_tokens_for(self, task_type: str) -> int:
        """Return the configured max_tokens for a task type, defaulting to
        the `general` bucket when the type has no explicit entry.
        """
        key = task_type.lower()
        return self.max_tokens.get(key, self.max_tokens.get("general", 96))


def load_policy(path: str | Path | None = None) -> Policy:
    """Load a Policy from a YAML file, or return defaults if `path` is None
    or the file does not exist.
    """
    if path is None:
        return Policy()
    file_path = Path(path)
    if not file_path.exists():
        return Policy()
    with file_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Policy file {file_path} must contain a YAML mapping")
    return Policy(**raw)


def _normalize_model_id(name: str) -> str:
    """Normalize a bare/prefixed model name to a full Fireworks model id."""
    stripped = name.strip()
    if stripped.startswith(FIREWORKS_MODEL_PREFIX):
        return stripped
    return f"{FIREWORKS_MODEL_PREFIX}{stripped}"


def parse_allowed_models(raw: str | None) -> list[str]:
    """Parse the ALLOWED_MODELS env var into a list of full model ids.

    Accepts, in order of attempt:
      1. A JSON array of strings: '["gpt-oss-20b", "glm-5p1"]'
      2. A comma-separated list: "gpt-oss-20b,glm-5p1"
    Each entry may be a bare name or already carry the
    "accounts/fireworks/models/" prefix. Blank/whitespace-only entries are
    dropped. Order is preserved; duplicates are removed keeping first
    occurrence.
    """
    if raw is None or not raw.strip():
        return []

    names: list[str]
    stripped_raw = raw.strip()
    if stripped_raw.startswith("["):
        parsed = json.loads(stripped_raw)
        if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
            raise ValueError("ALLOWED_MODELS JSON array must contain only strings")
        names = parsed
    else:
        names = stripped_raw.split(",")

    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        cleaned = name.strip()
        if not cleaned:
            continue
        full_id = _normalize_model_id(cleaned)
        if full_id not in seen:
            seen.add(full_id)
            result.append(full_id)
    return result


class Settings(BaseModel):
    """Runtime configuration sourced from environment variables."""

    fireworks_api_key: str
    fireworks_base_url: str = DEFAULT_FIREWORKS_BASE_URL
    allowed_models: list[str] = Field(default_factory=list)
    policy_path: str | None = None

    @field_validator("fireworks_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        """Build Settings from an environment mapping (defaults to os.environ).

        Raises ValueError if FIREWORKS_API_KEY is missing — fail fast at
        startup rather than surfacing an opaque 401 later.
        """
        source = env if env is not None else os.environ
        api_key = source.get("FIREWORKS_API_KEY", "").strip()
        if not api_key:
            raise ValueError("FIREWORKS_API_KEY is required and was not set")
        return cls(
            fireworks_api_key=api_key,
            fireworks_base_url=source.get("FIREWORKS_BASE_URL", DEFAULT_FIREWORKS_BASE_URL)
            or DEFAULT_FIREWORKS_BASE_URL,
            allowed_models=parse_allowed_models(source.get("ALLOWED_MODELS")),
            policy_path=source.get("ROUTING_POLICY_PATH"),
        )
