"""FastAPI demo app tests: healthz, dashboard HTML, Tier-0 /solve (zero
tokens, no network), Tier-1 /solve with the Fireworks HTTP call mocked via
respx, and /api/stats accumulation. No real network calls are made.
"""

from __future__ import annotations

import importlib

import httpx
import respx
from fastapi.testclient import TestClient

_BASE_URL = "https://api.fireworks.ai/inference/v1"


def _chat_response(content: str, prompt_tokens: int, completion_tokens: int):
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
        },
    )


def _demo_mode_module(monkeypatch):
    """Import a fresh `webapp` module with no FIREWORKS_API_KEY set, so its
    module-level `state = AppState()` boots in demo mode.
    """
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    monkeypatch.delenv("ALLOWED_MODELS", raising=False)
    import routing_agent.webapp as webapp_module

    return importlib.reload(webapp_module)


def _live_module(monkeypatch):
    """Import a fresh `webapp` module with a fake API key and one allowed
    model, so its module-level `state = AppState()` boots with a real
    (mockable) FireworksClient.
    """
    monkeypatch.setenv("FIREWORKS_API_KEY", "fw_test")
    monkeypatch.setenv("ALLOWED_MODELS", "accounts/fireworks/models/gpt-oss-20b")
    monkeypatch.setenv("FIREWORKS_BASE_URL", _BASE_URL)
    import routing_agent.webapp as webapp_module

    return importlib.reload(webapp_module)


def test_healthz_returns_ok(monkeypatch):
    webapp_module = _demo_mode_module(monkeypatch)
    client = TestClient(webapp_module.app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_serves_html_dashboard(monkeypatch):
    webapp_module = _demo_mode_module(monkeypatch)
    client = TestClient(webapp_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Routing Agent" in response.text
    assert "Route &amp; Solve" in response.text or "Route & Solve" in response.text


def test_solve_tier0_arithmetic_uses_zero_tokens_no_network(monkeypatch):
    webapp_module = _demo_mode_module(monkeypatch)
    client = TestClient(webapp_module.app)

    response = client.post("/solve", json={"prompt": "2 + 2"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "4"
    assert body["route"]["tier"] == 0
    assert body["route"]["model"] is None
    assert body["tokens"] == {"prompt": 0, "completion": 0, "total": 0}
    assert body["cost_usd"] == 0.0
    assert body["savings_pct"] == 100.0
    assert body["baseline_estimate_tokens"] > 0


def test_solve_rejects_empty_prompt(monkeypatch):
    webapp_module = _demo_mode_module(monkeypatch)
    client = TestClient(webapp_module.app)

    response = client.post("/solve", json={"prompt": "   "})

    assert response.status_code == 422


def test_solve_demo_mode_returns_503_for_model_needing_prompt(monkeypatch):
    webapp_module = _demo_mode_module(monkeypatch)
    client = TestClient(webapp_module.app)

    response = client.post("/solve", json={"prompt": "Tell me an interesting fact about otters."})

    assert response.status_code == 503
    assert "demo mode" in response.json()["detail"]


@respx.mock
def test_solve_tier1_model_path_with_mocked_fireworks_client(monkeypatch):
    respx.post(f"{_BASE_URL}/chat/completions").mock(
        return_value=_chat_response(
            "Fact: otters hold hands.", prompt_tokens=100, completion_tokens=12
        )
    )
    webapp_module = _live_module(monkeypatch)
    client = TestClient(webapp_module.app)

    response = client.post("/solve", json={"prompt": "Tell me an interesting fact about otters."})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Fact: otters hold hands."
    assert body["route"]["tier"] == 1
    assert body["route"]["model"] == "accounts/fireworks/models/gpt-oss-20b"
    assert body["tokens"]["total"] == 112
    assert body["cost_usd"] > 0
    assert 0 <= body["savings_pct"] <= 100


@respx.mock
def test_stats_accumulate_across_multiple_solve_calls(monkeypatch):
    respx.post(f"{_BASE_URL}/chat/completions").mock(
        return_value=_chat_response("answer text", prompt_tokens=100, completion_tokens=10)
    )
    webapp_module = _live_module(monkeypatch)
    client = TestClient(webapp_module.app)

    baseline_stats = client.get("/api/stats").json()
    assert baseline_stats["solved_count"] == 0
    assert baseline_stats["demo_mode"] is False

    client.post("/solve", json={"prompt": "2 + 2"})  # Tier 0, zero tokens
    client.post("/solve", json={"prompt": "Tell me an interesting fact."})  # Tier 1

    stats = client.get("/api/stats").json()

    assert stats["solved_count"] == 2
    assert stats["total_calls"] == 1
    assert stats["total_raw_tokens"] == 110
    assert stats["tier_call_distribution"] == {"tier1": 1}
    assert stats["baseline_estimate_tokens"] > 0
    assert 0 <= stats["savings_pct"] <= 100


def test_stats_demo_mode_flag_reflects_missing_api_key(monkeypatch):
    webapp_module = _demo_mode_module(monkeypatch)
    client = TestClient(webapp_module.app)

    stats = client.get("/api/stats").json()

    assert stats["demo_mode"] is True
    assert stats["total_calls"] == 0
