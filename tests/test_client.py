"""Client tests: retry-once-with-larger-cap on empty content, and TokenLedger
accounting. All HTTP calls are mocked with respx — no network.
"""

from __future__ import annotations

import httpx
import respx

from routing_agent.client import FireworksClient
from routing_agent.registry import KNOWN_MODELS

_BASE_URL = "https://api.fireworks.ai/inference/v1"
_GPT_OSS_20B = KNOWN_MODELS["accounts/fireworks/models/gpt-oss-20b"]
_DEEPSEEK_FLASH = KNOWN_MODELS["accounts/fireworks/models/deepseek-v4-flash"]


def _chat_response(content: str, prompt_tokens: int, completion_tokens: int, cached: int = 0):
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
                "prompt_tokens_details": {"cached_tokens": cached},
            },
        },
    )


@respx.mock
def test_complete_records_call_in_ledger():
    route = respx.post(f"{_BASE_URL}/chat/completions").mock(
        return_value=_chat_response("42", prompt_tokens=90, completion_tokens=3, cached=10)
    )
    client = FireworksClient(api_key="fw_test", base_url=_BASE_URL)

    result = client.complete(
        model_info=_GPT_OSS_20B,
        messages=[{"role": "user", "content": "2+2?"}],
        max_tokens=64,
        route="tier1:t1",
    )

    assert route.called
    assert result.content == "42"
    assert len(client.ledger.records) == 1
    record = client.ledger.records[0]
    assert record.prompt_tokens == 90
    assert record.completion_tokens == 3
    assert record.cached_tokens == 10
    assert record.retry is False
    assert record.route == "tier1:t1"


@respx.mock
def test_complete_retries_once_on_empty_content():
    route = respx.post(f"{_BASE_URL}/chat/completions").mock(
        side_effect=[
            _chat_response("", prompt_tokens=90, completion_tokens=64),
            _chat_response("57.8", prompt_tokens=90, completion_tokens=10),
        ]
    )
    client = FireworksClient(api_key="fw_test", base_url=_BASE_URL)

    result = client.complete(
        model_info=_GPT_OSS_20B,
        messages=[{"role": "user", "content": "17% of 340?"}],
        max_tokens=64,
        route="tier1:t2",
    )

    assert route.call_count == 2
    assert result.content == "57.8"
    assert result.retried is True
    # Both attempts (including the empty one) are ledgered.
    assert len(client.ledger.records) == 2
    assert client.ledger.records[0].retry is False
    assert client.ledger.records[1].retry is True


@respx.mock
def test_complete_second_call_uses_larger_max_tokens_on_retry():
    captured_payloads: list[dict] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        captured_payloads.append(payload)
        if len(captured_payloads) == 1:
            return _chat_response("", prompt_tokens=90, completion_tokens=64)
        return _chat_response("done", prompt_tokens=90, completion_tokens=5)

    respx.post(f"{_BASE_URL}/chat/completions").mock(side_effect=_capture)
    client = FireworksClient(api_key="fw_test", base_url=_BASE_URL)

    client.complete(
        model_info=_GPT_OSS_20B,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=64,
        route="tier1:t3",
    )

    assert len(captured_payloads) == 2
    assert captured_payloads[1]["max_tokens"] > captured_payloads[0]["max_tokens"]


@respx.mock
def test_complete_merges_reasoning_profile_params():
    import json

    captured: list[dict] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _chat_response("ok", prompt_tokens=90, completion_tokens=5)

    respx.post(f"{_BASE_URL}/chat/completions").mock(side_effect=_capture)
    client = FireworksClient(api_key="fw_test", base_url=_BASE_URL)

    client.complete(
        model_info=_GPT_OSS_20B,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=64,
        route="tier1:t4",
    )

    assert captured[0]["reasoning_effort"] == "low"


@respx.mock
def test_complete_skips_reasoning_profile_when_disabled():
    """The eval harness's --baseline mode must reflect a naive/untuned
    deployment, so it opts out of the registry's reasoning-suppression
    profile via apply_reasoning_profile=False.
    """
    import json

    captured: list[dict] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _chat_response("ok", prompt_tokens=90, completion_tokens=5)

    respx.post(f"{_BASE_URL}/chat/completions").mock(side_effect=_capture)
    client = FireworksClient(api_key="fw_test", base_url=_BASE_URL)

    client.complete(
        model_info=_GPT_OSS_20B,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=64,
        route="baseline:t4",
        apply_reasoning_profile=False,
    )

    assert "reasoning_effort" not in captured[0]


@respx.mock
def test_complete_floors_max_tokens_at_model_min_viable():
    import json

    captured: list[dict] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _chat_response("ok", prompt_tokens=20, completion_tokens=5)

    respx.post(f"{_BASE_URL}/chat/completions").mock(side_effect=_capture)
    client = FireworksClient(api_key="fw_test", base_url=_BASE_URL)

    # gpt-oss-20b has min_viable_max_tokens=64; request a tighter cap.
    client.complete(
        model_info=_GPT_OSS_20B,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=8,
        route="tier1:t5",
    )

    assert captured[0]["max_tokens"] >= _GPT_OSS_20B.min_viable_max_tokens


def test_ledger_total_raw_tokens_sums_all_calls():
    from routing_agent.client import TokenLedger
    from routing_agent.models import CallRecord

    ledger = TokenLedger()
    ledger.record(CallRecord(model="m1", prompt_tokens=10, completion_tokens=5))
    ledger.record(CallRecord(model="m1", prompt_tokens=20, completion_tokens=8))
    assert ledger.total_raw_tokens == 43


def test_ledger_total_price_weighted_uses_registry_pricing():
    from routing_agent.client import TokenLedger
    from routing_agent.models import CallRecord

    ledger = TokenLedger()
    ledger.record(
        CallRecord(
            model=_DEEPSEEK_FLASH.id,
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
        )
    )
    total = ledger.total_price_weighted({_DEEPSEEK_FLASH.id: _DEEPSEEK_FLASH})
    expected = _DEEPSEEK_FLASH.price_in + _DEEPSEEK_FLASH.price_out
    assert total == expected


def test_ledger_price_weighted_ignores_unknown_model():
    from routing_agent.client import TokenLedger
    from routing_agent.models import CallRecord

    ledger = TokenLedger()
    ledger.record(CallRecord(model="unknown-model", prompt_tokens=100, completion_tokens=100))
    assert ledger.total_price_weighted({}) == 0.0
