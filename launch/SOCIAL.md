# Social Drafts — DRAFT ONLY, DO NOT POST

These are drafts for a human to review, edit, and publish manually. No
platform, MCP, or automation should be used to post, schedule, or send any of
the text below. Every number traces to `evals/reports/tuned-live.json` and
`evals/README.md`.

---

## LinkedIn Post — DRAFT — DO NOT POST

*(193 words)*

> Most AI agent demos show off what the model can do. Ours is scored on the
> opposite thing: how little it has to call the model at all.
>
> Track 1 of the AMD Developer Cloud Hackathon scores submissions on total
> Fireworks AI tokens spent, above an accuracy bar. So instead of routing
> every task to the strongest model, we built a tiered cascade: a
> zero-token deterministic layer for arithmetic, dates, strings, units, and
> extraction, then the cheapest adequate model for everything else, with a
> single confidence-gated escalation as the last resort.
>
> Three numbers from our 200-task live eval against the real Fireworks API:
>
> — 99.5% accuracy (199/200 correct)
> — 32.5% of tasks solved with zero LLM tokens
> — ~47–51% total token reduction vs. an honest strongest-model baseline
>
> The whole 200-task run cost $0.0037 and took 26 seconds.
>
> We also fell short of our internal 60% reduction stretch goal, and we're
> saying so — the honest limitations are in the writeup, not hidden. Routing
> intelligence beat raw compute here, but it has a floor.
>
> Link: [placeholder — add repo/demo URL before posting]
>
> #AMDHackathon #LLMRouting #AIEngineering #FireworksAI #TokenEfficiency

---

## X / Twitter Thread — DRAFT — DO NOT POST

**Tweet 1/5 (hook):**
> Most AI agents are scored on what they can do. Ours was scored on how rarely it has to call an LLM at all.
>
> Built for the AMD Dev Cloud Hackathon's token-efficiency track. Here's what a routing-first agent looks like 🧵

**Tweet 2/5:**
> The cascade: classify for free → solve deterministically if possible (arithmetic, dates, strings, units, extraction) → cheapest adequate model if not → single escalation to the strongest model only if the cheap one fails a confidence check.

**Tweet 3/5:**
> Results from a 200-task live eval against the real Fireworks API:
> • 99.5% accuracy (199/200)
> • 32.5% of tasks solved with ZERO tokens
> • ~47–51% fewer tokens vs. an honest "just use the strongest model" baseline
> • $0.0037 total cost, 26 seconds

**Tweet 4/5:**
> We didn't hit our internal 60% reduction stretch goal — the honest number is 47–51%, capped by fixed per-call overhead on the models we used. Saying that out loud because judges (and you) can read an eval report.

**Tweet 5/5 (CTA):**
> Full writeup + eval reports + demo: [placeholder — add link before posting]
>
> If you're building for a token/cost-scored track: the model choice matters less than the decision not to call one.

---

## Short Variants

**X / short-video hook (one line, for a video caption or opening title card):**
> "One in three tasks, zero tokens. Here's the routing agent that only calls an LLM when it actually has to."

**Alt hook (leads with the honesty angle instead):**
> "99.5% accurate, ~50% fewer tokens than the naive approach — and here's exactly where it fell short."
