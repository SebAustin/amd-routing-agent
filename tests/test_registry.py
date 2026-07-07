"""Registry tests: ALLOWED_MODELS resolution, unknown-id tier inference, and
the Gemma-partner-prize preference at equal price tier (SC6).
"""

from __future__ import annotations

from routing_agent.registry import (
    KNOWN_MODELS,
    ModelInfo,
    SizeTier,
    cheapest,
    resolve_allowed,
    strongest,
)


def test_resolve_allowed_intersects_known_models():
    allowed = resolve_allowed(
        [
            "accounts/fireworks/models/gpt-oss-20b",
            "accounts/fireworks/models/deepseek-v4-flash",
        ]
    )
    assert len(allowed) == 2
    assert allowed[0].id == "accounts/fireworks/models/gpt-oss-20b"
    assert allowed[0].family == "gpt-oss"
    assert allowed[1].family == "deepseek"


def test_resolve_allowed_infers_tier_for_unknown_id_by_size_marker():
    allowed = resolve_allowed(["accounts/fireworks/models/some-new-70b-model"])
    assert len(allowed) == 1
    assert allowed[0].tier == SizeTier.MEDIUM


def test_resolve_allowed_infers_tier_for_1b_and_120b_markers():
    nano = resolve_allowed(["accounts/fireworks/models/tiny-1b-chat"])[0]
    large = resolve_allowed(["accounts/fireworks/models/mega-120b-chat"])[0]
    assert nano.tier == SizeTier.NANO
    assert large.tier == SizeTier.LARGE


def test_resolve_allowed_infers_gemma_family_from_name():
    allowed = resolve_allowed(["accounts/fireworks/models/gemma-9-99b-it"])
    assert allowed[0].family == "gemma"
    assert allowed[0].is_gemma is True


def test_resolve_allowed_infers_qwen_and_llama_families():
    qwen = resolve_allowed(["accounts/fireworks/models/qwen-2-72b"])[0]
    llama = resolve_allowed(["accounts/fireworks/models/llama-3-8b"])[0]
    assert qwen.family == "qwen"
    assert llama.family == "llama"


def test_cheapest_prefers_gemma_at_equal_price_tier():
    """SC6 / Gemma-partner-prize hook: when a gemma* model and a
    non-gemma model of equal blended price are both allowed, `cheapest`
    must select the gemma model.
    """
    gemma_candidate = ModelInfo(
        id="accounts/fireworks/models/gemma-test-equal",
        family="gemma",
        price_in=0.10,
        price_out=0.30,
        tier=SizeTier.SMALL,
        capabilities=frozenset({"general"}),
    )
    non_gemma_candidate = ModelInfo(
        id="accounts/fireworks/models/other-test-equal",
        family="other",
        price_in=0.10,
        price_out=0.30,
        tier=SizeTier.SMALL,
        capabilities=frozenset({"general"}),
    )
    result = cheapest("general", [non_gemma_candidate, gemma_candidate])
    assert result is not None
    assert result.is_gemma is True
    assert result.id == "accounts/fireworks/models/gemma-test-equal"


def test_cheapest_falls_back_to_non_gemma_when_no_gemma_allowed():
    non_gemma_cheap = ModelInfo(
        id="accounts/fireworks/models/cheap-model",
        family="other",
        price_in=0.05,
        price_out=0.05,
        tier=SizeTier.NANO,
        capabilities=frozenset({"general"}),
    )
    non_gemma_expensive = ModelInfo(
        id="accounts/fireworks/models/expensive-model",
        family="other",
        price_in=1.0,
        price_out=1.0,
        tier=SizeTier.FLAGSHIP,
        capabilities=frozenset({"general"}),
    )
    result = cheapest("general", [non_gemma_expensive, non_gemma_cheap])
    assert result is not None
    assert result.is_gemma is False
    assert result.id == "accounts/fireworks/models/cheap-model"


def test_cheapest_still_picks_strictly_cheaper_non_gemma_over_pricier_gemma():
    # Gemma preference only applies at equal price tier, not unconditionally.
    cheap_non_gemma = ModelInfo(
        id="accounts/fireworks/models/cheap-non-gemma",
        family="other",
        price_in=0.02,
        price_out=0.02,
        tier=SizeTier.NANO,
        capabilities=frozenset({"general"}),
    )
    pricier_gemma = ModelInfo(
        id="accounts/fireworks/models/pricier-gemma",
        family="gemma",
        price_in=0.50,
        price_out=0.50,
        tier=SizeTier.MEDIUM,
        capabilities=frozenset({"general"}),
    )
    result = cheapest("general", [cheap_non_gemma, pricier_gemma])
    assert result is not None
    assert result.id == "accounts/fireworks/models/cheap-non-gemma"


def test_cheapest_filters_by_capability():
    generalist = ModelInfo(
        id="accounts/fireworks/models/generalist",
        family="other",
        price_in=0.05,
        price_out=0.05,
        tier=SizeTier.NANO,
        capabilities=frozenset({"general"}),
    )
    coder = ModelInfo(
        id="accounts/fireworks/models/coder",
        family="other",
        price_in=0.20,
        price_out=0.20,
        tier=SizeTier.MEDIUM,
        capabilities=frozenset({"general", "code"}),
    )
    result = cheapest("code", [generalist, coder])
    assert result is not None
    assert result.id == "accounts/fireworks/models/coder"


def test_cheapest_returns_none_when_no_candidate_supports_capability():
    generalist = ModelInfo(
        id="accounts/fireworks/models/generalist",
        family="other",
        price_in=0.05,
        price_out=0.05,
        tier=SizeTier.NANO,
        capabilities=frozenset({"classification"}),
    )
    result = cheapest("code", [generalist])
    assert result is None


def test_cheapest_returns_none_for_empty_allowed_list():
    assert cheapest("general", []) is None


def test_strongest_returns_highest_quality_rank():
    allowed = resolve_allowed(
        [
            "accounts/fireworks/models/gpt-oss-20b",
            "accounts/fireworks/models/kimi-k2p6",
            "accounts/fireworks/models/glm-5p1",
        ]
    )
    result = strongest(allowed)
    assert result is not None
    assert result.id == "accounts/fireworks/models/kimi-k2p6"


def test_strongest_returns_none_for_empty_allowed_list():
    assert strongest([]) is None


def test_known_models_seeded_with_plan_facts():
    gpt_oss_20b = KNOWN_MODELS["accounts/fireworks/models/gpt-oss-20b"]
    assert gpt_oss_20b.reasoning_profile == {"reasoning_effort": "low"}
    assert gpt_oss_20b.min_viable_max_tokens >= 64
    assert gpt_oss_20b.prompt_overhead_tokens == 82

    deepseek_flash = KNOWN_MODELS["accounts/fireworks/models/deepseek-v4-flash"]
    assert deepseek_flash.prompt_overhead_tokens == 14

    gemma_1b = KNOWN_MODELS["accounts/fireworks/models/gemma-3-1b-it"]
    assert gemma_1b.serverless is False
    assert gemma_1b.is_gemma is True
