"""Fireworks API client wrapper: request shaping, reasoning-profile merging,
retry-once-with-larger-cap on empty content, and token ledger accounting.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from openai import OpenAI

from routing_agent.models import CallRecord
from routing_agent.registry import ModelInfo

logger = logging.getLogger(__name__)

# Multiplier applied to max_tokens on the single empty-content retry.
_RETRY_MAX_TOKENS_MULTIPLIER = 3


@dataclass
class TokenLedger:
    """Accumulates CallRecords and exposes raw/price-weighted totals.

    Kept as a plain accumulator (not a global singleton) so each router run
    (or eval run) can own an isolated ledger.
    """

    records: list[CallRecord] = field(default_factory=list)

    def record(self, call: CallRecord) -> None:
        self.records.append(call)

    @property
    def total_raw_tokens(self) -> int:
        return sum(record.total_tokens for record in self.records)

    def total_price_weighted(self, models: dict[str, ModelInfo]) -> float:
        """Total USD cost across all recorded calls, using registry pricing.

        Calls against a model id absent from `models` contribute zero cost
        (rather than raising) since price-weighted is a secondary, hedge
        metric — raw token count is the primary scoring assumption.
        """
        total = 0.0
        for call in self.records:
            info = models.get(call.model)
            if info is None:
                continue
            total += (call.prompt_tokens / 1_000_000) * info.price_in
            total += (call.completion_tokens / 1_000_000) * info.price_out
        return total

    def calls_for_task(self, route: str) -> list[CallRecord]:
        return [r for r in self.records if r.route == route]


@dataclass
class CompletionResult:
    """The extracted answer text plus the raw usage for ledger recording."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    retried: bool


class FireworksClient:
    """Thin wrapper over the OpenAI SDK pointed at the Fireworks endpoint.

    Every `complete()` call is recorded into the supplied `TokenLedger`,
    including retries, so ledger totals always reflect true billed usage.
    """

    def __init__(self, api_key: str, base_url: str, ledger: TokenLedger | None = None) -> None:
        self._sdk = OpenAI(api_key=api_key, base_url=base_url)
        self.ledger = ledger if ledger is not None else TokenLedger()

    def complete(
        self,
        model_info: ModelInfo,
        messages: list[dict[str, str]],
        max_tokens: int,
        stop: list[str] | None = None,
        route: str = "",
        temperature: float = 0.0,
        apply_reasoning_profile: bool = True,
    ) -> CompletionResult:
        """Issue a chat completion, retrying once with a larger cap if the
        first attempt returns empty content (the reasoning-token trap:
        gpt-oss burns budget on hidden reasoning_content before any visible
        content is emitted).

        The model's `reasoning_profile` params are merged into the request
        to suppress/limit reasoning, unless `apply_reasoning_profile=False`
        (used by the eval harness's `--baseline` mode, which must reflect a
        naive/untuned deployment rather than benefit from this router's own
        reasoning-suppression tuning — see evals/run_eval.py). `max_tokens`
        is floored at the model's `min_viable_max_tokens` so a
        caller-supplied tight cap never triggers a guaranteed-empty first
        call.
        """
        effective_max_tokens = max(max_tokens, model_info.min_viable_max_tokens)
        result = self._call(
            model_info,
            messages,
            effective_max_tokens,
            stop,
            route,
            temperature,
            retry=False,
            apply_reasoning_profile=apply_reasoning_profile,
        )
        if result.content.strip():
            return result

        logger.info(
            "empty content on first attempt, retrying with larger cap",
            extra={"model": model_info.id, "route": route},
        )
        retry_max_tokens = effective_max_tokens * _RETRY_MAX_TOKENS_MULTIPLIER
        return self._call(
            model_info,
            messages,
            retry_max_tokens,
            stop,
            route,
            temperature,
            retry=True,
            apply_reasoning_profile=apply_reasoning_profile,
        )

    def _call(
        self,
        model_info: ModelInfo,
        messages: list[dict[str, str]],
        max_tokens: int,
        stop: list[str] | None,
        route: str,
        temperature: float,
        retry: bool,
        apply_reasoning_profile: bool = True,
    ) -> CompletionResult:
        request_kwargs: dict[str, object] = {
            "model": model_info.id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stop:
            request_kwargs["stop"] = stop
        if apply_reasoning_profile:
            request_kwargs.update(model_info.reasoning_profile)

        started = time.monotonic()
        response = self._sdk.chat.completions.create(**request_kwargs)
        latency_ms = (time.monotonic() - started) * 1000

        choice = response.choices[0]
        content = choice.message.content or ""
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        cached_tokens = 0
        if usage is not None and usage.prompt_tokens_details is not None:
            cached_tokens = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0

        self.ledger.record(
            CallRecord(
                model=model_info.id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
                latency_ms=latency_ms,
                route=route,
                retry=retry,
            )
        )

        return CompletionResult(
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            retried=retry,
        )
