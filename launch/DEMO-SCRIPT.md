# Demo Script — Hybrid Token-Efficient Routing Agent

Target length: 2.5–3 minutes. Narrated screen recording of the live dashboard
(`webapp.py`, `GET /`, `POST /solve`, `GET /api/stats`) per `DEPLOYMENT.md`.
Hand this to `ai-video-producer` for the recorded cut.

Every number below is pulled from `evals/reports/tuned-live.json` (200-task
live run against the real Fireworks API). Do not ad-lib different numbers on
camera — if the dashboard shows a slightly different figure on the day of
recording (live run jitter), say the number on screen, not the number in this
script.

---

## Shot 1 — Cold open: the leaderboard problem (0:00–0:10)

**On screen:** Black/dark slide, title card only: "AMD Hackathon ACT II — Track 1: fewest Fireworks tokens above an accuracy bar."

**Voiceover:**
> "Track 1 doesn't score you on what your agent can do. It scores you on how few tokens it needs to do it — while staying accurate. Most teams will point every task at the biggest model and call it done. That's the expensive way."

---

## Shot 2 — Architecture slide (0:10–0:40)

**On screen:** The cascade diagram (reuse from `launch/DECK.md` slide 3 / `PLAN.md` §3):
```
task -> classifier (0 tokens)
     -> Tier 0: deterministic solvers (0 tokens)
     -> Tier 1: cheapest adequate model, confidence-gated
     -> Tier 2: single escalation to the strongest model
```

**Voiceover:**
> "Our routing agent asks one question before it ever calls an LLM: does this task actually need one? A regex-and-AST classifier catches arithmetic, date math, string ops, unit conversion, and extraction — and solves them for zero tokens. Everything else goes to the cheapest model that can handle it, gated by a confidence check. Only tasks that fail that gate escalate — once — to the strongest model. No retries loop, no self-verification tax."

---

## Shot 3 — Live dashboard demo, Tier 0 (0:40–1:05)

**On screen:** `GET /` dashboard open in browser. Type into the `/solve` prompt box.

**Prompt to type (real evalset task `arithmetic-001`):**
```
What is 847 * 36?
```

**Action:** Submit. Dashboard shows route = `tier0`, tokens = `0`, savings = `100%` for this task, answer = `30492`.

**Voiceover:**
> "Watch the route field. 'What is 847 times 36' — that's real arithmetic, correctly answered, zero Fireworks tokens spent. No model was called. In our 200-task eval set, 65 tasks — just under a third — resolve exactly this way."

---

## Shot 4 — Live dashboard demo, Tier 1 (1:05–1:45)

**On screen:** Same dashboard, new prompt.

**Prompt to type (real evalset task `classification-001`):**
```
Classify the sentiment of this review as one of: positive, negative, neutral. Review: "This is the best purchase I've made all year, absolutely love it!"
```

**Action:** Submit. Dashboard shows route = `tier1:gpt-oss-20b`, token count for this call, answer = `positive`, correct.

**Voiceover:**
> "This one needs a model — it's sentiment classification. The router picks the cheapest model that's adequate for the job, gpt-oss-20b, with a minimal prompt, temperature zero, and reasoning suppressed so it doesn't burn completion tokens thinking out loud. Notice the token count — small, and it's what actually gets billed, not an estimate."

---

## Shot 5 — Savings counter climbing (1:45–2:05)

**On screen:** `GET /api/stats` panel or dashboard's cumulative counter, showing running totals as a few more prompts are submitted in quick succession (can be sped up 2x in editing).

**Voiceover:**
> "Every call — Tier 0 or Tier 1 — updates a running ledger: raw tokens, price-weighted cost, and route distribution. That's the same ledger the eval harness uses to score the full 200-task run."

---

## Shot 6 — Eval numbers screen (2:05–2:35)

**On screen:** Static results table (build from `evals/reports/tuned-live.json`):

| Metric | Value |
|---|---|
| Accuracy | 99.5% (199/200) |
| Zero-token tasks (Tier 0) | 65/200 — 32.5% |
| Token reduction vs. honest baseline | ~47–51% |
| Total cost, 200 tasks | $0.003742 |
| Wall-clock time, 200 tasks | 25.88s |
| Retry rate | 2.1% |

**Voiceover:**
> "Across the full 200-task eval set: 99.5% accuracy — 199 out of 200 correct. Thirty-two and a half percent of tasks never touch a model at all. And against an honest baseline — same tasks, strongest model, no routing tricks — total token spend drops by roughly 47 to 51%. The whole run costs a third of a cent and finishes in under 26 seconds."

**Note for editor:** say "roughly 47 to 51 percent," not a single fixed number — the eval README documents this as a measured range from stratified baseline sampling, not a point estimate.

---

## Shot 7 — Gemma + close (2:35–2:55)

**On screen:** Registry code snippet or diagram showing `cheapest_allowed(capability)` with a `gemma*` preference marker; then final title card with repo link.

**Voiceover:**
> "One more thing: the model registry auto-prefers Gemma at equal price tier whenever the harness allows it — that's unit-tested and ready today. On July 7th, when we probed the live Fireworks account, Gemma wasn't exposed on serverless, so this run routes through gpt-oss and DeepSeek instead. The preference activates automatically the moment Gemma becomes available — no code change needed.
>
> Routing intelligence, not raw compute. That's the whole pitch."

**On screen (final card):** repo link placeholder, "AMD Developer Cloud Hackathon — ACT II, Track 1."

---

## Fallback if something fails live

If the live `/solve` call errors, times out, or the Fireworks API is flaky during recording:

1. **Tier-0 shot (Shot 3):** This never depends on the network — the classifier and AST solver run locally. If it still fails, fall back to a pre-recorded screen capture of the same `arithmetic-001` prompt from an earlier successful run.
2. **Tier-1 shot (Shot 4):** If the live call fails or is slow, cut to a pre-recorded clip of the same `classification-001` prompt captured during eval prep, and say on camera: "here's a capture from our eval run" instead of pretending it's live.
3. **Eval numbers (Shot 6):** This is always a static screen built from the committed `evals/reports/tuned-live.json` — it has no live-failure risk. If earlier shots fail, extend this segment and lean on it as the proof point.
4. **Absolute fallback:** If the dashboard is unavailable entirely, skip straight from Shot 2 (architecture) to Shot 6 (eval numbers) and narrate the cascade using the route-distribution table instead of a live call. Mention it was "run against the live API earlier" — do not claim it's happening live if it isn't.
