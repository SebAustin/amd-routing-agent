# Pitch Deck — Hybrid Token-Efficient Routing Agent

AMD Developer Cloud Hackathon, ACT II Track 1. 8 slides, one H2 per slide,
speaker notes below each. Render slides with an existing presentation skill
(`anthropic-pptx` or equivalent) — author the narrative here, don't hand-build
slide XML. Constrain any generated output to `launch/`.

Every number on these slides traces to `evals/reports/tuned-live.json` and
`evals/README.md`. No projected or aspirational figures are presented as
results.

---

## Slide 1 — Tokens Are Money at Scale

**Content:**
- Track 1 is scored on Fireworks token count above an accuracy threshold — not on feature count.
- At hackathon scale, the difference between "call the strongest model every time" and "call the right thing every time" is the entire leaderboard.
- One line, large type: **"The cheapest correct answer wins — not the smartest-sounding one."**

**Speaker notes:** Open with the constraint, not the solution. Judges are already scoring on tokens; we don't need to sell them on why tokens matter. State it and move.

---

## Slide 2 — The Insight

**Content:**
- Most tasks in a real workload don't need a frontier model.
- A meaningful fraction don't need a model at all.
- "847 × 36" is arithmetic, not a reasoning problem. Sentiment classification of one sentence doesn't need chain-of-thought.
- The win isn't a better model. It's not calling one when you don't have to, and calling the cheapest adequate one when you do.

**Speaker notes:** This is the thesis slide. Keep it to the one idea — routing intelligence beats compute — everything after this proves it.

---

## Slide 3 — Architecture: The Cascade

**Content (diagram):**
```
task
  -> TaskClassifier (0 tokens: regex/heuristics)
      |
      +-- Tier 0: deterministic solvers (0 tokens)
      |   arithmetic (safe AST eval), date math, string ops,
      |   unit conversion, regex extraction
      |   fires only when it can self-validate
      |
      +-- Tier 1: cheapest adequate allowed model
      |   minimal prompt, temperature=0, reasoning suppressed
      |   -> ConfidenceGate (format validation + Tier-0 cross-check
      |      + answer-token logprobs)
      |      pass -> answer
      |      fail -> Tier 2
      |
      +-- Tier 2: single escalation to strongest allowed model
          never loops, no LLM self-verification
```

**Speaker notes:** Walk it top to bottom exactly once. Emphasize "single escalation, never loops" — that's a deliberate token-safety property, not a limitation. The confidence gate's primary check is deterministic (format + Tier-0 cross-check); logprobs are secondary because live probing showed the token stream mixes reasoning-channel tokens with answer tokens.

---

## Slide 4 — The Token-Efficiency Toolbox

**Content (5 techniques, one line each):**
1. **Zero-token Tier 0** — deterministic solvers answer arithmetic, dates, strings, units, and extraction without touching an LLM.
2. **Cheapest-adequate routing** — Tier 1 always picks the lowest-cost model that can handle the task's capability tag, not the biggest available.
3. **Reasoning suppression** — per-model profiles (`reasoning_effort: low`, thinking toggles) stop models like gpt-oss-20b from burning completion tokens on hidden `reasoning_content`.
4. **Minimal prompts + answer-only contracts** — ≤10-token system text, per-task-type `max_tokens` caps and stop sequences; no boilerplate instructions repeated per call.
5. **Single-escalation confidence gate** — Tier 1 output is validated (format + Tier-0 cross-check, logprobs as secondary signal) before falling through to Tier 2 exactly once — never a self-verification loop, which would cost more tokens than it saves.

**Speaker notes:** This is the "how," concretely. Every one of these five is in the committed source (`registry.py`, `classifier.py`, `prompts.py`, `router.py`, `solvers/`), not a roadmap item.

---

## Slide 5 — Results

**Content (table, from `evals/reports/tuned-live.json` + `evals/README.md`):**

| Metric | Value |
|---|---|
| Accuracy (200-task live eval) | 99.5% (199/200) |
| Zero-token tasks (Tier 0) | 65/200 — 32.5% |
| Token reduction vs. honest baseline | ~47–51% |
| Total price-weighted cost, 200 tasks | $0.003742 |
| Wall-clock time, 200 tasks | 25.88s |
| Retry rate | 2.1% |
| Route distribution | Tier 0: 65 · gpt-oss-20b: 75 · gpt-oss-120b: 48 · deepseek-v4-flash: 10 · Tier 2 escalation: 2 |

**Speaker notes:** The baseline for the token-reduction number is a genuinely naive deployment — same tasks, strongest allowed model, generic prompts, reasoning suppression explicitly disabled — not the routing agent competing against a strawman. State the range (47–51%), not a single cherry-picked number; it comes from stratified sampling of the baseline, documented in `evals/README.md`.

---

## Slide 6 — Honest Limitations

**Content:**
- **SC2 stretch target (≥60% token reduction) not met.** Measured 47–51%, short of the stretch goal. The remaining cost floor is structural: gpt-oss's ~82-token fixed chat-template overhead plus a ~96–128-completion-token floor required to let its hidden reasoning channel finish without truncating — verified by testing that a lower floor reintroduces the exact truncation bug this pass fixed.
- **One residual eval failure** (`summarization-003`): a correct paraphrase drops the literal keyword the `contains_all` grader requires. Diminishing returns to chase further on a 5-task category.
- **Gemma is not live on this Fireworks account today** (probed July 7 — all Gemma variants return `NOT_FOUND`). See next slide.
- **Retry accounting is real, not hidden**: 2.1% retry rate, and retry tokens are counted in the reported totals, not subtracted out.

**Speaker notes:** Lead with what didn't hit target. Judges read eval reports for a living — a deck that only shows green numbers reads as incomplete, not impressive.

---

## Slide 7 — Gemma & the AMD Stack

**Content:**
- The model registry auto-prefers `gemma*` models at equal price tier — this is unit-tested and active in the code today, independent of whether Gemma is reachable.
- Live probe (July 7, real API key, `GET /models` + direct calls): all Gemma variants returned `NOT_FOUND` on this Fireworks serverless account.
- The moment a `gemma*` model is added to `ALLOWED_MODELS` — via a hackathon proxy or AMD Developer Cloud self-hosting — the registry preference activates with zero code changes.
- This is deliberately honest phrasing: we are not claiming Gemma ran in this eval. We are claiming the routing logic already knows how to prefer it.

**Speaker notes:** Say this plainly and don't oversell it. "The registry prefers Gemma; Gemma wasn't available to us on the day we probed" is the whole truth and it's a fine thing to say out loud.

---

## Slide 8 — Team, Repo, Links

**Content:**
- Repo: `github.com/SebAustin/amd-routing-agent` (per `DEPLOYMENT.md`) — `[unverified: confirm repo is public before sharing this link]`
- Demo: Hugging Face Space `SebAustin/amd-routing-agent-demo` — `[unverified: DEPLOYMENT.md marks this "Pending" as of the last read; confirm live before the deck goes out]`
- Docs: `README.md`, `PLAN.md`, `SECURITY.md`, `DEPLOYMENT.md` in the repo.
- Built for AMD Developer Cloud Hackathon, ACT II — Track 1.

**Speaker notes:** Confirm both links resolve before presenting live — do not present an unconfirmed Space URL as already live.
