"""Model metadata registry.

Holds live-probed facts about Fireworks-hosted models (§2 of PLAN.md):
pricing, capability tags, quality tier, prompt overhead, and reasoning
suppression profiles. `resolve_allowed` intersects this registry with the
harness-supplied `ALLOWED_MODELS`, inferring metadata for unknown ids from
name heuristics. `cheapest` and `strongest` implement the Tier-1/Tier-2
selection policy, including the Gemma-partner-prize preference: at equal
price tier, a `gemma*` model is always preferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum

FIREWORKS_MODEL_PREFIX = "accounts/fireworks/models/"


class Capability(str):
    """Capability tags a model may be suited for. Plain str subclass so the
    registry can accept ad-hoc tags without an exhaustive enum.
    """


CAPABILITY_TAGS = frozenset(
    {"math", "code", "extraction", "classification", "general", "long_form"}
)


class SizeTier(IntEnum):
    """Coarse capability/size ranking used for cheapest/strongest selection.

    Lower is cheaper/smaller. Ties within a tier are broken by price, then by
    the Gemma preference.
    """

    NANO = 0  # ~1-4B
    SMALL = 1  # ~8-20B
    MEDIUM = 2  # ~27-70B
    LARGE = 3  # ~120B+
    FLAGSHIP = 4  # top-tier proprietary-scale (kimi, glm, deepseek-pro, ...)


@dataclass(frozen=True)
class ModelInfo:
    """Metadata for a single Fireworks-servable model.

    Attributes:
        id: Full Fireworks model id (e.g. "accounts/fireworks/models/gpt-oss-20b").
        family: Model family name (e.g. "gpt-oss", "gemma").
        price_in: USD per 1M input tokens.
        price_out: USD per 1M output tokens.
        tier: Coarse size/capability tier.
        capabilities: Set of capability tags this model is adequate for.
        quality_rank: Higher = stronger/more capable, used for Tier-2 escalation.
        prompt_overhead_tokens: Estimated fixed chat-template token overhead.
        reasoning_profile: Extra request params merged in to suppress/limit
            reasoning (e.g. {"reasoning_effort": "low"} for gpt-oss family).
        min_viable_max_tokens: Minimum max_tokens to reliably get non-empty
            content back (reasoning models burn budget on hidden thinking).
        serverless: Whether this model is currently callable on the probed
            account (informational only; ALLOWED_MODELS is the real gate).
    """

    id: str
    family: str
    price_in: float
    price_out: float
    tier: SizeTier
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"general"}))
    quality_rank: int = 0
    prompt_overhead_tokens: int = 20
    reasoning_profile: dict[str, object] = field(default_factory=dict)
    min_viable_max_tokens: int = 16
    serverless: bool = True

    @property
    def is_gemma(self) -> bool:
        return self.family == "gemma"

    @property
    def price_avg(self) -> float:
        """Blended per-M price used for cheapest/tier comparisons."""
        return (self.price_in + self.price_out) / 2


def _model_id(name: str) -> str:
    """Normalize a bare model name to a full Fireworks model id."""
    if name.startswith(FIREWORKS_MODEL_PREFIX):
        return name
    return f"{FIREWORKS_MODEL_PREFIX}{name}"


_GENERAL_CAPS = frozenset({"general", "classification", "extraction"})
_FULL_CAPS = frozenset({"general", "classification", "extraction", "math", "code", "long_form"})

# Live-probed facts (PLAN.md §2, probed July 7 with the real key):
# - gpt-oss-20b/120b: reasoning models; burn completion tokens on hidden
#   reasoning_content unless reasoning_effort is suppressed AND max_tokens is
#   generous enough for reasoning + content.
# - deepseek-v4-flash: low overhead (~14 tok) but inlines thinking into
#   `content` when truncated -> needs a generous cap and answer extraction.
# - Gemma family: NOT_FOUND on this account today; kept in the registry with
#   `serverless=False` so the Gemma-preference logic is demonstrable and
#   activates automatically the moment ALLOWED_MODELS includes one.
KNOWN_MODELS: dict[str, ModelInfo] = {
    _model_id("gpt-oss-20b"): ModelInfo(
        id=_model_id("gpt-oss-20b"),
        family="gpt-oss",
        price_in=0.07,
        price_out=0.30,
        tier=SizeTier.SMALL,
        capabilities=_GENERAL_CAPS,
        quality_rank=2,
        prompt_overhead_tokens=82,
        reasoning_profile={"reasoning_effort": "low"},
        # Eval-tuned (evals/run_eval.py ladder step d): gpt-oss rejects
        # reasoning_effort="none" (400 invalid_request_error), so its hidden
        # <|channel|>analysis reasoning trace still has to complete before
        # the final-channel answer is emitted. Probed live: a date-math
        # reasoning trace needed ~101 completion tokens end-to-end and was
        # truncated mid-analysis (leaking raw channel markers into content)
        # at 64/96; 128 gives consistent headroom.
        min_viable_max_tokens=128,
        serverless=True,
    ),
    _model_id("gpt-oss-120b"): ModelInfo(
        id=_model_id("gpt-oss-120b"),
        family="gpt-oss",
        price_in=0.15,
        price_out=0.60,
        tier=SizeTier.LARGE,
        capabilities=_FULL_CAPS,
        quality_rank=6,
        prompt_overhead_tokens=82,
        reasoning_profile={"reasoning_effort": "low"},
        # Eval-tuned: same trap as gpt-oss-20b above, confirmed live on this
        # model too (96 truncated a date-math reasoning trace mid-analysis;
        # 128 completed cleanly at 101 completion tokens).
        min_viable_max_tokens=128,
        serverless=True,
    ),
    _model_id("deepseek-v4-flash"): ModelInfo(
        id=_model_id("deepseek-v4-flash"),
        family="deepseek",
        price_in=0.10,
        price_out=0.40,
        tier=SizeTier.SMALL,
        capabilities=_GENERAL_CAPS | {"code"},
        quality_rank=3,
        prompt_overhead_tokens=14,
        reasoning_profile={},
        # Thinking inlines into content when truncated; give it room.
        min_viable_max_tokens=48,
        serverless=True,
    ),
    _model_id("deepseek-v4-pro"): ModelInfo(
        id=_model_id("deepseek-v4-pro"),
        family="deepseek",
        price_in=0.90,
        price_out=2.70,
        tier=SizeTier.FLAGSHIP,
        capabilities=_FULL_CAPS,
        quality_rank=9,
        prompt_overhead_tokens=14,
        # Eval-tuned: this is the Tier-2 escalation model, so a leaked/
        # truncated reasoning trace here is the worst case (last resort,
        # single call, no further fallback). Probed live: with no
        # reasoning_profile, a tight cap truncated mid "We are asked: ..."
        # chain-of-thought before any answer token (0/2 multiple-choice
        # escalations correct). `reasoning_effort="none"` is accepted by
        # this model (unlike gpt-oss) and eliminates the leak entirely —
        # completion_tokens dropped from 32 (truncated) to 2-27 (clean
        # answer) across probed prompts.
        reasoning_profile={"reasoning_effort": "none"},
        min_viable_max_tokens=32,
        serverless=True,
    ),
    _model_id("glm-5p1"): ModelInfo(
        id=_model_id("glm-5p1"),
        family="glm",
        price_in=0.20,
        price_out=0.80,
        tier=SizeTier.MEDIUM,
        capabilities=_FULL_CAPS,
        quality_rank=5,
        prompt_overhead_tokens=20,
        reasoning_profile={},
        min_viable_max_tokens=24,
        serverless=True,
    ),
    _model_id("glm-5p2"): ModelInfo(
        id=_model_id("glm-5p2"),
        family="glm",
        price_in=0.35,
        price_out=1.20,
        tier=SizeTier.FLAGSHIP,
        capabilities=_FULL_CAPS,
        quality_rank=7,
        prompt_overhead_tokens=20,
        reasoning_profile={},
        min_viable_max_tokens=24,
        serverless=True,
    ),
    _model_id("kimi-k2p5"): ModelInfo(
        id=_model_id("kimi-k2p5"),
        family="kimi",
        price_in=0.60,
        price_out=2.50,
        tier=SizeTier.FLAGSHIP,
        capabilities=_FULL_CAPS,
        quality_rank=8,
        prompt_overhead_tokens=20,
        reasoning_profile={},
        min_viable_max_tokens=24,
        serverless=True,
    ),
    _model_id("kimi-k2p6"): ModelInfo(
        id=_model_id("kimi-k2p6"),
        family="kimi",
        price_in=0.75,
        price_out=3.00,
        tier=SizeTier.FLAGSHIP,
        capabilities=_FULL_CAPS,
        quality_rank=10,
        prompt_overhead_tokens=20,
        reasoning_profile={},
        min_viable_max_tokens=24,
        serverless=True,
    ),
    # Gemma family: preferred at equal tier once available (see `cheapest`).
    # Not currently serverless-callable on the probed account (NOT_FOUND).
    _model_id("gemma-3-1b-it"): ModelInfo(
        id=_model_id("gemma-3-1b-it"),
        family="gemma",
        price_in=0.02,
        price_out=0.02,
        tier=SizeTier.NANO,
        capabilities=_GENERAL_CAPS,
        quality_rank=1,
        prompt_overhead_tokens=15,
        reasoning_profile={},
        min_viable_max_tokens=16,
        serverless=False,
    ),
    _model_id("gemma-3-4b-it"): ModelInfo(
        id=_model_id("gemma-3-4b-it"),
        family="gemma",
        price_in=0.04,
        price_out=0.04,
        tier=SizeTier.NANO,
        capabilities=_GENERAL_CAPS,
        quality_rank=2,
        prompt_overhead_tokens=15,
        reasoning_profile={},
        min_viable_max_tokens=16,
        serverless=False,
    ),
    _model_id("gemma-3-12b-it"): ModelInfo(
        id=_model_id("gemma-3-12b-it"),
        family="gemma",
        price_in=0.07,
        price_out=0.07,
        tier=SizeTier.SMALL,
        capabilities=_GENERAL_CAPS | {"code"},
        quality_rank=3,
        prompt_overhead_tokens=15,
        reasoning_profile={},
        min_viable_max_tokens=16,
        serverless=False,
    ),
    _model_id("gemma-3-27b-it"): ModelInfo(
        id=_model_id("gemma-3-27b-it"),
        family="gemma",
        price_in=0.10,
        price_out=0.10,
        tier=SizeTier.MEDIUM,
        capabilities=_FULL_CAPS,
        quality_rank=4,
        prompt_overhead_tokens=15,
        reasoning_profile={},
        min_viable_max_tokens=16,
        serverless=False,
    ),
    _model_id("gemma-4-e4b"): ModelInfo(
        id=_model_id("gemma-4-e4b"),
        family="gemma",
        price_in=0.04,
        price_out=0.04,
        tier=SizeTier.NANO,
        capabilities=_GENERAL_CAPS,
        quality_rank=2,
        prompt_overhead_tokens=15,
        reasoning_profile={},
        min_viable_max_tokens=16,
        serverless=False,
    ),
    _model_id("gemma-4-26b-a4b-it"): ModelInfo(
        id=_model_id("gemma-4-26b-a4b-it"),
        family="gemma",
        price_in=0.09,
        price_out=0.09,
        tier=SizeTier.MEDIUM,
        capabilities=_FULL_CAPS,
        quality_rank=4,
        prompt_overhead_tokens=15,
        reasoning_profile={},
        min_viable_max_tokens=16,
        serverless=False,
    ),
    _model_id("gemma-4-31b-it"): ModelInfo(
        id=_model_id("gemma-4-31b-it"),
        family="gemma",
        price_in=0.11,
        price_out=0.11,
        tier=SizeTier.MEDIUM,
        capabilities=_FULL_CAPS,
        quality_rank=5,
        prompt_overhead_tokens=15,
        reasoning_profile={},
        min_viable_max_tokens=16,
        serverless=False,
    ),
}

# Ordered (pattern, tier, family_hint) heuristics for unknown model ids.
# First matching size pattern wins; family is inferred separately.
_SIZE_PATTERNS: tuple[tuple[re.Pattern[str], SizeTier], ...] = (
    (re.compile(r"(?<![0-9])1b(?![0-9])", re.IGNORECASE), SizeTier.NANO),
    (re.compile(r"(?<![0-9])(2b|3b|4b)(?![0-9])", re.IGNORECASE), SizeTier.NANO),
    (
        re.compile(r"(?<![0-9])(7b|8b|9b|12b|13b|14b|20b)(?![0-9])", re.IGNORECASE),
        SizeTier.SMALL,
    ),
    (
        re.compile(r"(?<![0-9])(26b|27b|30b|31b|32b|34b|70b)(?![0-9])", re.IGNORECASE),
        SizeTier.MEDIUM,
    ),
    (
        re.compile(r"(?<![0-9])(120b|235b|400b|671b)(?![0-9])", re.IGNORECASE),
        SizeTier.LARGE,
    ),
)

_FAMILY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"gemma", re.IGNORECASE), "gemma"),
    (re.compile(r"qwen", re.IGNORECASE), "qwen"),
    (re.compile(r"llama", re.IGNORECASE), "llama"),
    (re.compile(r"gpt-oss", re.IGNORECASE), "gpt-oss"),
    (re.compile(r"deepseek", re.IGNORECASE), "deepseek"),
    (re.compile(r"glm", re.IGNORECASE), "glm"),
    (re.compile(r"kimi", re.IGNORECASE), "kimi"),
    (re.compile(r"mixtral|mistral", re.IGNORECASE), "mistral"),
)

_TIER_PRICE_HINT: dict[SizeTier, tuple[float, float]] = {
    SizeTier.NANO: (0.03, 0.03),
    SizeTier.SMALL: (0.10, 0.35),
    SizeTier.MEDIUM: (0.20, 0.70),
    SizeTier.LARGE: (0.30, 1.00),
    SizeTier.FLAGSHIP: (0.60, 2.50),
}


def _infer_family(name: str) -> str:
    for pattern, family in _FAMILY_PATTERNS:
        if pattern.search(name):
            return family
    return "unknown"


def _infer_tier(name: str) -> SizeTier:
    for pattern, tier in _SIZE_PATTERNS:
        if pattern.search(name):
            return tier
    # No size hint at all -> assume mid-sized flagship-class model, since
    # most unlabeled hosted ids on Fireworks are large proprietary-scale.
    return SizeTier.FLAGSHIP


def _infer_model_info(model_id: str) -> ModelInfo:
    """Best-effort metadata for a model id absent from KNOWN_MODELS.

    Heuristics only use the bare name: size markers (-1b/-4b/8b/20b/70b/120b)
    and family keywords (gemma/qwen/llama/...). Unknown ids default to
    conservative general-purpose capabilities so they are never selected for
    tasks they might be inadequate for by silently over-promising.
    """
    bare_name = model_id.removeprefix(FIREWORKS_MODEL_PREFIX)
    family = _infer_family(bare_name)
    tier = _infer_tier(bare_name)
    price_in, price_out = _TIER_PRICE_HINT[tier]
    return ModelInfo(
        id=model_id,
        family=family,
        price_in=price_in,
        price_out=price_out,
        tier=tier,
        capabilities=_GENERAL_CAPS if tier <= SizeTier.SMALL else _FULL_CAPS,
        quality_rank=int(tier) * 2,
        prompt_overhead_tokens=20,
        reasoning_profile={},
        min_viable_max_tokens=32,
        serverless=True,
    )


def resolve_allowed(allowed_ids: list[str]) -> list[ModelInfo]:
    """Resolve harness-supplied allowed model ids into ModelInfo records.

    Ids already normalized to full Fireworks ids (see `config.py`). Known ids
    pull rich metadata from `KNOWN_MODELS`; unknown ids get heuristic tiering
    via `_infer_model_info` so the router degrades gracefully to new models.
    """
    resolved: list[ModelInfo] = []
    for model_id in allowed_ids:
        info = KNOWN_MODELS.get(model_id)
        resolved.append(info if info is not None else _infer_model_info(model_id))
    return resolved


def _supports(info: ModelInfo, capability: str) -> bool:
    return capability in info.capabilities or capability == "general"


def cheapest(capability: str, allowed: list[ModelInfo]) -> ModelInfo | None:
    """Return the cheapest model in `allowed` adequate for `capability`.

    Adequacy = the model declares the capability tag (or the request is
    "general", which every model satisfies). Among equally-cheap candidates
    (same price tier, compared on blended per-M price rounded to avoid float
    noise), a `gemma*` model is preferred — the Gemma-partner-prize hook.
    Ties beyond that are broken by lower SizeTier (prefer smaller/faster),
    then by model id for determinism.
    """
    candidates = [m for m in allowed if _supports(m, capability)]
    if not candidates:
        return None

    def sort_key(m: ModelInfo) -> tuple[float, int, int, str]:
        return (
            round(m.price_avg, 4),
            0 if m.is_gemma else 1,  # gemma preferred at equal price
            int(m.tier),
            m.id,
        )

    return min(candidates, key=sort_key)


def strongest(allowed: list[ModelInfo]) -> ModelInfo | None:
    """Return the highest quality_rank model in `allowed` (Tier-2 escalation).

    Ties broken by gemma preference, then by model id for determinism.
    """
    if not allowed:
        return None

    def sort_key(m: ModelInfo) -> tuple[int, int, str]:
        return (-m.quality_rank, 0 if m.is_gemma else 1, m.id)

    return min(allowed, key=sort_key)
