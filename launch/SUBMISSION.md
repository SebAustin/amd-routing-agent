# lablab.ai Submission — Copy-Paste Ready

Source of truth: `evals/reports/tuned-live.json`, `evals/README.md`, `PLAN.md`,
`SECURITY.md`, `DEPLOYMENT.md`. Every metric below traces to the committed
eval report. Nothing here is aspirational.

---

## Project Title

**Route First, Call Rarely**

(21 characters — well under the 60-char limit. Alternates below if a
different tone is wanted; pick one, don't mix.)

Alternates considered:
- "The Cascade Router" (19 chars) — accurate but generic, doesn't signal the token angle.
- "Zero-Token Routing Agent" (25 chars) — leads with the strongest single number (32.5% of tasks resolved free) but undersells the Tier 1/2 story.
- "Cheapest Correct Answer Wins" (29 chars) — punchier, matches the deck's thesis line, slightly more marketing-voice.

Recommendation: **"Route First, Call Rarely"** — short, describes the actual mechanism (classify before you spend), and isn't a hype phrase.

---

## Short Description (≤200 chars)

**Chosen (155 chars):**
> A routing agent that answers 1 in 3 tasks with zero LLM tokens, then picks the cheapest adequate model for the rest — 99.5% accurate, ~50% fewer tokens.

Character count: 155.

Alternate (176 chars), leads with the leaderboard framing:
> Built for a token-count leaderboard: a tiered router that solves arithmetic/dates/strings for free, escalates only when needed. 99.5% accuracy, 32.5% zero-token.

---

## Long Description (400–600 words)

## The problem

Track 1 of the AMD Developer Cloud Hackathon scores submissions on total
Fireworks AI tokens spent, above an accuracy threshold. The naive path —
route every task to the strongest available model — is the most expensive
possible way to pass. Most tasks in a realistic workload don't need a
frontier model's reasoning budget, and a meaningful fraction don't need a
model at all.

## The approach

We built a tiered routing cascade instead of a single-model agent:

1. **Tier 0 — deterministic solvers, zero tokens.** A regex/heuristic
   classifier identifies task type before any network call. Arithmetic
   (safe AST evaluation, not `eval`), date math, string operations, unit
   conversion, and regex-based extraction are solved locally. These solvers
   are precision-first: they only answer when they can self-validate,
   otherwise the task falls through to Tier 1.
2. **Tier 1 — cheapest adequate model.** Everything that needs a model goes
   to the lowest-cost model that can handle its capability tag — not the
   biggest one available. Prompts are minimal (answer-only contracts, ≤10
   tokens of system text), temperature is zero, and each model has a
   reasoning-suppression profile so models like `gpt-oss-20b` don't burn
   completion tokens on hidden chain-of-thought. A confidence gate —
   primarily output-format validation and Tier-0 cross-checks, secondarily
   answer-token logprobs — decides whether the answer is trustworthy.
3. **Tier 2 — single escalation.** Anything the confidence gate rejects
   escalates exactly once to the strongest allowed model, then the answer is
   accepted. No retry loops, no LLM self-verification — those cost more
   tokens than they recover.

Every model call is recorded in a token ledger (raw tokens and
price-weighted cost) so the savings numbers below are measured, not
estimated.

## Results (200-task live eval against the real Fireworks API)

- **99.5% accuracy** (199/200 correct) across arithmetic, dates, strings,
  units, extraction, classification, multiple-choice, short QA, code, and
  summarization.
- **32.5% of tasks (65/200) resolved with zero Fireworks tokens** — Tier 0
  alone, no model call.
- **~47–51% token reduction** versus an honest baseline (same 200 tasks,
  strongest allowed model, generic prompts, reasoning suppression explicitly
  disabled to reflect a genuinely naive deployment).
- **$0.003742 total price-weighted cost** for the full 200-task run,
  completed in **25.88 seconds**.
- **2.1% retry rate** — and retry tokens are counted in every total above,
  not subtracted out.
- Route distribution: Tier 0 handled 65 tasks; `gpt-oss-20b` handled 75;
  `gpt-oss-120b` handled 48; `deepseek-v4-flash` handled 10; only 2 tasks
  needed Tier 2 escalation.

## What we're honest about

We fell short of our internal stretch target of 60% token reduction — the
measured 47–51% is limited by gpt-oss's fixed chat-template overhead and a
completion-token floor its reasoning channel needs to avoid truncating. One
eval task fails on a grading technicality (a correct paraphrase missing a
literal required keyword). And Gemma — the partner model this hackathon
track highlights — was not reachable on our Fireworks account when we probed
the live API on July 7; the model registry auto-prefers `gemma*` models at
equal price tier and this preference is unit-tested, but it has not run
against a live Gemma endpoint in this eval.

## Why it fits the track

This submission treats "fewest tokens above an accuracy bar" as an
architecture problem, not a prompting problem. The routing decision — not
the model — is where the token budget is won or lost.

---

## Technology Tags

`Python` · `FastAPI` · `Fireworks AI` · `LLM Routing` · `OpenAI SDK`
(OpenAI-compatible client) · `Docker` · `Pydantic` · `Pytest` · `AMD
Developer Cloud`

---

## Category Tags

`Developer Tools` · `AI Agents` · `Cost Optimization` · `LLM
Infrastructure` · `Hackathon — Track 1 (Token Efficiency)`

---

## Cover Image — Art Direction

**Composition:** A vertical cascade/funnel motif, three horizontal bands
stacked top to bottom, each narrower than the last — visually representing
the Tier 0 → Tier 1 → Tier 2 routing cascade. The top band (Tier 0) is the
widest and rendered as a simple geometric shape (e.g., a solved equation
fragment or a checkmark glyph) to suggest "resolved without a model." The
narrowing bands below use increasingly dense, textured geometric patterns
(circuit-trace-like linework, not literal circuitry) to suggest escalating
computational cost.

**Palette:** Dark background (near-black, `#0A0A0A`–`#121212`) with AMD red
(`#ED1C24`) as the single accent color, used sparingly — on the cascade
dividing lines, on a small token-counter numeral, and on one glyph in the
top band. Supporting neutral: cool gray (`#8A8A8A`) for secondary linework.
No gradients that read as "generic AI blob art" — keep edges crisp and
geometric.

**Elements:**
- A small, stylized token-counter readout in one corner (monospace numerals
  ticking down or a small "0 tokens" tag on the top band) — communicates the
  cost angle without a paragraph of text.
- The cascade/funnel shape as the dominant compositional element, off-center
  (rule-of-thirds placement), not centered and symmetrical.
- Negative space dominates — avoid cluttering the image with icons for every
  technology used.

**Explicitly avoid:** No AMD logo or wordmark reproduction — this is an
original composition inspired by AMD's red-on-black brand energy, not a
reuse of AMD's actual marks. No stock "neural network" clipart, no generic
robot/brain imagery, no photorealistic humans.
