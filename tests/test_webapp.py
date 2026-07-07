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


# --- SECURITY.md M-2: per-IP rate limiting -----------------------------


def test_rate_limit_allows_requests_within_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "3")
    webapp_module = _demo_mode_module(monkeypatch)
    client = TestClient(webapp_module.app)

    for _ in range(3):
        response = client.post("/solve", json={"prompt": "2 + 2"})
        assert response.status_code == 200


def test_rate_limit_returns_429_with_friendly_json_over_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    webapp_module = _demo_mode_module(monkeypatch)
    client = TestClient(webapp_module.app)

    client.post("/solve", json={"prompt": "2 + 2"})
    client.post("/solve", json={"prompt": "3 + 3"})
    response = client.post("/solve", json={"prompt": "4 + 4"})

    assert response.status_code == 429
    body = response.json()
    assert "detail" in body
    assert "rate limit" in body["detail"].lower()


def test_rate_limit_is_per_ip_not_global(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    webapp_module = _demo_mode_module(monkeypatch)
    client = TestClient(webapp_module.app)

    first = client.post("/solve", json={"prompt": "2 + 2"}, headers={"X-Forwarded-For": "10.0.0.1"})
    second = client.post(
        "/solve", json={"prompt": "3 + 3"}, headers={"X-Forwarded-For": "10.0.0.2"}
    )
    third_same_ip_as_first = client.post(
        "/solve", json={"prompt": "5 + 5"}, headers={"X-Forwarded-For": "10.0.0.1"}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third_same_ip_as_first.status_code == 429


def test_rate_limit_honors_x_forwarded_for_first_ip(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    webapp_module = _demo_mode_module(monkeypatch)
    client = TestClient(webapp_module.app)

    # Same real client (first hop) behind two different proxy chains ->
    # still rate limited as one identity because the first XFF entry matches.
    first = client.post(
        "/solve",
        json={"prompt": "2 + 2"},
        headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1"},
    )
    second = client.post(
        "/solve",
        json={"prompt": "3 + 3"},
        headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.99"},
    )

    assert first.status_code == 200
    assert second.status_code == 429


def test_rate_limit_default_is_ten_per_minute(monkeypatch):
    webapp_module = _demo_mode_module(monkeypatch)

    assert webapp_module.state.rate_limiter.limit == 10


def test_sliding_window_rate_limiter_evicts_expired_hits():
    from routing_agent.webapp import SlidingWindowRateLimiter

    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=10.0)

    assert limiter.allow("k", now=0.0) is True
    assert limiter.allow("k", now=1.0) is False  # still within window
    assert limiter.allow("k", now=11.0) is True  # window has rolled past


# --- SECURITY.md M-2: daily spend cap -----------------------------------


@respx.mock
def test_solve_returns_503_once_daily_budget_exceeded(monkeypatch):
    monkeypatch.setenv("DEMO_DAILY_BUDGET_USD", "0.0000001")
    respx.post(f"{_BASE_URL}/chat/completions").mock(
        return_value=_chat_response("answer text", prompt_tokens=100, completion_tokens=10)
    )
    webapp_module = _live_module(monkeypatch)
    client = TestClient(webapp_module.app)

    first = client.post("/solve", json={"prompt": "Tell me an interesting fact."})
    assert first.status_code == 200

    second = client.post("/solve", json={"prompt": "Tell me another interesting fact."})

    assert second.status_code == 503
    assert "demo budget reached for today" in second.json()["detail"]


def test_tier0_solve_still_works_after_budget_exceeded(monkeypatch):
    # No respx mock registered: Tier-0 must never reach the network, budget
    # cap or not.
    monkeypatch.setenv("DEMO_DAILY_BUDGET_USD", "0.0000001")
    webapp_module = _live_module(monkeypatch)
    client = TestClient(webapp_module.app)

    # Force the budget tracker into an already-exceeded state directly,
    # simulating a day's worth of prior model-path spend.
    webapp_module.state.budget_tracker.budget_usd = -1.0

    response = client.post("/solve", json={"prompt": "2 + 2"})

    assert response.status_code == 200
    assert response.json()["answer"] == "4"


def test_daily_budget_tracker_resets_on_utc_day_rollover(monkeypatch):
    import routing_agent.webapp as webapp_module

    ledger = webapp_module.TokenLedger()
    tracker = webapp_module.DailyBudgetTracker(budget_usd=1.0)

    class _FixedDay:
        value = "2026-07-07"

    monkeypatch.setattr(tracker, "_today", lambda: _FixedDay.value)
    assert tracker.spent_today_usd(ledger, {}) == 0.0

    tracker._records_at_day_start = 5  # pretend "today" already saw records
    _FixedDay.value = "2026-07-08"  # UTC day rolls over

    tracker._roll_if_new_day(ledger)

    assert tracker._day == "2026-07-08"
    assert tracker._records_at_day_start == 0
