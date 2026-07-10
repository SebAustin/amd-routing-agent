# POSTMORTEM — Hybrid Token-Efficient Routing Agent (AMD Hackathon ACT II, Track 1)

**Retro date:** 2026-07-07 · **Lead:** retrospective/coach role · **Posture:** blameless, evidence-based

This is a learning document, not a scorecard. Every observation ties to an artifact (PLAN.md,
ASSUMPTIONS.md, ACCEPTANCE.md, SECURITY.md, evals/README.md, git history). Root causes are
process/role/skill gaps, never people. Project-specific notes stay here; candidates worth
generalizing are called out and carried into `SKILL-UPDATES.md` for a **gated** decision.

---

## 1. Headline metrics

| Metric | Result | Source |
|---|---|---|
| Wall-clock time | ~1 day vs 4 budgeted (Day-4 integration buffer left untouched) | git log dates (all commits 2026-07-07) |
| Live API spend | ≈ $0.15 total; tuned 200-task run costs $0.0037 | ACCEPTANCE.md §Quality gates |
| Plan loop | **PASS 90/100 on iteration 1** (1 round) | PLAN.md r2 revision log |
| Build/verify loop | **SOLID 97/100 on iteration 1** (0 FIX rounds) | ACCEPTANCE.md header |
| Tests | 175 passed; ruff clean; 200/200 eval tasks valid | ACCEPTANCE.md §Quality gates |
| Commits | 25, small and single-purpose | git log |
| Success criteria | 5/6 PASS (SC1/SC3/SC4/SC5/SC6); SC2 **honest miss** (~47–51% vs 60% stretch) | ACCEPTANCE.md §Success criteria |
| Security | STRIDE audit, 0 CRITICAL / 0 HIGH; M-1 fixed in code, M-2 fixed in webapp | SECURITY.md §5 |

**Success-criteria detail:** SC1 99.5% (199/200), SC3 32.5% zero-token (65/200), SC4 passed
as-scoped (image build green in CI; in-container runtime run deferred — local Docker daemon
never came up), SC5 clean (no secret in history, verified twice), SC6 unit-tested and dormant
(Gemma NOT_FOUND on this account). SC2 was explicitly re-labelled a **stretch** target during
the plan loop, so missing it is a documented shortfall, not a broken commitment.

---

## 2. Timeline (what happened, in order)

1. **Intake + live probe (Day 1 morning).** Requirements + assumptions logged. Critically, the
   real Fireworks key was probed **before** the architecture was frozen. Four facts surfaced for
   pennies that would each have been a mid-build surprise: Gemma is NOT serverless despite the
   partner prize; unlisted models (`gpt-oss-20b`, `deepseek-v4-flash`) are callable so `/models`
   is not authoritative; a reasoning-token trap burns completion tokens on hidden channels; and
   per-model chat-template prompt overhead is real (~82 tokens for gpt-oss).
2. **Plan loop — 1 iteration.** `plan-critic` returned PASS 90/100 with advisories, all folded
   in: SC2 marked stretch + retry-token accounting added; the logprobs advisory triggered a
   30-second live probe that **materially changed the design** (format-validation became the
   PRIMARY confidence gate, logprobs demoted to secondary); the ungrounded eval-mix assumption
   became risk 4b; Day 4 was reserved for integration + submission only to fix Day-4 overload.
3. **Parallel build, wave 1.** Core routing package and the eval set were built in parallel
   under strict file-boundary + single-git-owner rules. One lint leak crossed the boundary
   (`evals/graders.py`) — trivially fixed.
4. **Parallel build, wave 2.** Eval-tuning and webapp/Docker built in parallel. The eval-tuning
   agent found **9 real bugs** (8 classifier regex bugs, 4 Tier-0 solver precision bugs
   including 4 wrong-at-full-confidence Tier-0 answers, reasoning-channel traps) and, unprompted,
   made the SC2 baseline *fairer* (`apply_reasoning_profile=False`, ADR-0004), which **halved
   the reported win but preserved honesty**.
5. **Security audit.** STRIDE pass: 0 CRITICAL/HIGH. M-1 (adapter input-size/count cap) fixed in
   code with regression tests; M-2 (webapp rate limit + $1/day budget cap) fixed.
6. **Build/verify — 1 iteration.** `solution-verifier` scored SOLID 97/100 with zero FIX rounds.
7. **Docs + deploy prep.** Full doc set + launch material. HF Space deploy fully prepared but
   **blocked at the gate**: the provided HF token was read-only, so the approved Space deploy
   reduced to one gated script awaiting a write-scoped user credential.

---

## 3. What went well

- **Probe-before-architecture was the single highest-leverage move.** Spending pennies against
  the live key on Day 1 turned four latent mid-build surprises into design inputs. The
  format-primary confidence gate — the core of the final design — exists *because* the logprobs
  probe happened before the plan was frozen, not after.
- **Honesty held under pressure.** The eval-tuning agent chose to make the comparison baseline
  fairer even though it cut the headline SC2 number roughly in half, and the team reported SC2
  as an honest FAIL rather than shopping for a flattering baseline. ADR-0004 records the choice.
  The eval README even flags that the committed `default-*`/`tuned-*` reports share policy values
  and are *not* a true before/after — refusing to overclaim its own evidence.
- **Parallelism paid off with discipline.** Two build waves ran in parallel with only one trivial
  cross-boundary lint leak, because file boundaries and a single git owner were set up front.
- **Eval-as-audit caught defects early.** The 200-task eval run functioned as a correctness audit
  and surfaced 9 real bugs — including wrong-at-full-confidence Tier-0 answers — before they could
  reach the verifier or the leaderboard.
- **Clean loops.** Plan passed on iteration 1; build was SOLID on iteration 1. No wasted FIX
  cycles, and the 4-day budget was met in ~1 day with the integration buffer intact.
- **Guardrails behaved.** The permission classifier correctly blocked delegating a secret-transfer
  to a subagent; the orchestrator split the work rather than routing a secret through a delegate.
  Commits used explicit paths; no secret entered history (verified twice).

## 4. What was hard / friction

- **Shell-less doc-writer couldn't run its own verification gate.** `doc-writer` has tools
  `Read, Write, Edit, Grep, Glob` — **no Bash** — so it could not verify the commands/paths it
  documents. The orchestrator ran the gate instead. Worse, without Bash the agent inspected git
  via Glob and **wrongly concluded "no .git"** when the repo is in fact a git repo — a false
  negative that could have propagated into the docs.
- **Local Docker daemon never came up headlessly.** The in-container harness runtime run (part of
  SC4) could not execute locally. Mitigated by a CI `docker-build` job that proves the image
  builds; runtime behavior is identical by construction because `adapter.py` is runtime-agnostic.
  SC4 still passed *as scoped*, but a success criterion partly rested on a construction argument
  rather than an executed run.
- **HF token scope discovered at deploy time, not intake.** The approved HF Space deploy was
  fully built, then blocked because the provided token was **read-only**. Nothing in intake
  checked the scope of the credentials for the planned external services, so a known-required
  capability failed at the last mile instead of being flagged on Day 1.
- **SC2 stretch missed (~47–51% vs 60%).** Root cause is documented and structural: gpt-oss's
  fixed ~82-token chat-template overhead plus the ~96–128 completion-token floor its hidden
  reasoning channel needs to complete without truncating. Lowering the floor reintroduces the
  exact truncation bug that was fixed this pass. This is a real ceiling, well-explained.
- **Minor cross-boundary lint leak** in `evals/graders.py` during parallel wave 1 — trivially
  fixed, but evidence that parallel file boundaries need an explicit owner-of-shared-files rule.

---

## 5. Root causes (process/role/skill — not people)

| # | Symptom | Root cause | Scope |
|---|---------|-----------|-------|
| RC1 | Four env facts (Gemma serverless, unlisted models, reasoning trap, prompt overhead) could have been mid-build surprises | Live-environment probing is not a required step of the plan/architecture phase; it happened here by good instinct, not by process | **Generalizable** |
| RC2 | One cross-boundary lint leak; parallel builds worked only because ad-hoc rules were set up | No documented parallel-builder protocol (file boundaries + single git owner + shared-file ownership) in the orchestration manual | **Generalizable** |
| RC3 | doc-writer could not run its verification gate; wrongly concluded "no .git" | doc-writer's own instructions tell it to "verify commands and paths exist" but it lacks the Bash tool to do so; no fallback rule assigns the gate to the orchestrator for shell-less roles | **Generalizable** |
| RC4 | HF write-scope failure surfaced at deploy, blocking an approved deliverable | Credential *presence* is checked, but credential *scope* for every planned external service is not preflighted at intake | **Generalizable** |
| RC5 | SC2 headline could have been inflated by an unfair baseline | Honesty held only because an individual agent chose it; no explicit "honest-baseline" principle for comparative metrics is written into the rubric | **Generalizable** |
| RC6 | SC4 in-container runtime run deferred | Local Docker daemon unavailable in this environment — an environment limitation, not a process gap | **Project-specific** |
| RC7 | SC2 missed the 60% stretch | Structural model-overhead ceiling (chat template + reasoning floor); correctly documented | **Project-specific** |

---

## 6. Project-specific notes (stay here)

- Rotate the Fireworks key after the hackathon — it was pasted in chat (ASSUMPTIONS.md #12).
  History is clean, but the value was exposed outside the repo.
- To complete SC4's in-container runtime run, execute the harness image on a host with a live
  Docker daemon (or in CI with a run step), then attach the `/output/results.json` as evidence.
- HF Space deploy is one command away once a write-scoped token exists:
  `HF_TOKEN=hf_xxx ./scripts/deploy_space.sh`.
- SC2 is a genuine ceiling for the current allowed-model set; the only lever left is a cheaper
  Tier-1 model with lower fixed overhead (e.g. a serverless Gemma, if the harness exposes one).
- The committed `default-*` and `tuned-*` eval reports share policy values and are **not** a
  true before/after (evals/README.md §Note). Keep this caveat if the reports are cited anywhere.

---

## 7. Generalizable lessons (carried to SKILL-UPDATES.md — proposals only, gated)

1. **Probe the live environment before finalizing the plan.** (RC1) → plan-rubric criterion +
   architect step.
2. **Parallel-builder protocol** (file boundaries + single git owner + shared-file ownership).
   (RC2) → agency-orchestration pattern.
3. **Shell-less roles can't own their verification gate.** (RC3) → doc-writer prompt + an
   orchestration fallback rule.
4. **Credential-scope preflight at intake** for *all* planned external services. (RC4) →
   requirements-analyst step + a plan-rubric completeness check.
5. **Honest-baseline principle** for any comparative/headline metric. (RC5) → solution-rubric
   criterion note + architect/eval guidance.

All five are **additive** and **tightening-only** (they add checks; none relaxes a guardrail or
lowers a bar). Each is written up with a target file, exact change, and evidence in
`SKILL-UPDATES.md`, and **none is applied without explicit user approval on a feature branch**.

---

## Addendum — post-acceptance phases (2026-07-08 → 07-10)

**Addendum date:** 2026-07-10 · same blameless, evidence-based posture. The original sections
above are unchanged. After acceptance, three more phases ran; the user has since **explicitly
approved** applying the needed team-skill updates (proposals 1, 2, 3a, 4, 5), and this addendum
records two further generalizable lessons (proposals 6–7) surfaced by these phases. Evidence:
git log since `d1e7308` (commits `852a8a6`, `14c3d79`, `b6971e3`, `cb0a9b5`, `8d4be94`,
`4b538c1`, `11eaade`), `launch/`, `scripts/video/`, `scripts/assets/`, `.github/workflows/ci.yml`,
and the `ACCEPTANCE.md` Deferred-list updates.

### Timeline

1. **HF Space deploy completed (2026-07-08).** After the user supplied a **write-scoped** token,
   the previously-gated deploy ran and went live (ACCEPTANCE.md Deferred #4, now DONE:
   `https://sebaustin-amd-routing-agent-demo.hf.space`; Tier-0 at 0 tokens, model path via
   `gpt-oss-20b` verified). This **confirms RC4 was a credential-*scope* issue, not a presence
   issue** — the exact failure mode proposal 4 preflights.
2. **Demo video production (2026-07-08).** A fully scripted pipeline: `edge-tts` narration,
   Playwright recording of the **live** Space, `ffmpeg` assembly — 168s / 1080p, verified
   frame-by-frame (`scripts/video/`, `launch/video`).
3. **Submission assets (2026-07-10).** A ≤2000-char description (1884 chars), a 16:9 cover, and
   an 8-slide PDF deck (`scripts/assets/`, `launch/cover.png`, `launch/deck.pdf`,
   `launch/SUBMISSION.md`). The orchestrator then **reconciled all assets to `tuned-live.json`
   as the single canonical source** (commit `8d4be94`).
4. **GHCR publish (2026-07-10).** A CI `docker-publish` job pushes the harness image to
   `ghcr.io/sebaustin/amd-routing-agent` using only the built-in `GITHUB_TOKEN`
   (`packages: write`), verified by anonymous pull (`.github/workflows/ci.yml`, commit
   `4b538c1`).

### What worked

- **The clean-room CI runner closed the local-environment gaps.** The local Docker daemon was
  still unavailable headlessly (the same limitation as RC6), so the image publish ran in CI with
  the built-in token and an anonymous-pull verification. This is the **practical answer to RC6**:
  when the local environment can't execute a step, a CI runner with a scoped built-in credential
  can — without introducing a user secret.
- **Canonical-source reconciliation held.** The video agent correctly pulled numbers from the
  committed `tuned-live.json`, and the orchestrator swept every downstream asset to that one
  source before submission. Honesty and single-source discipline carried through the last mile.
- **Credential-scope theory confirmed in practice.** RC4's fix (write-scoped token) unblocked the
  deploy on the first try once the correctly-scoped credential existed — validating proposal 4.

### What didn't (friction)

- **Local `ffmpeg` had no libass/drawtext — discovered mid-build.** The caption step was designed
  assuming subtitle burn-in, but the local `ffmpeg` build shipped without the subtitle/drawtext
  filters. Worked around by rendering captions as Chromium PNGs and compositing with an `overlay`
  filter. A `ffmpeg -filters | grep subtitles`-style capability probe **before** designing the
  caption step would have caught this at plan time.
- **Metric jitter had propagated into older launch copy.** The video agent's use of the canonical
  `tuned-live.json` exposed drift: `$0.003742 / 2.1%` (canonical) vs a stale `$0.003636 / 1.45%`
  that had already reached some published copy — run-to-run jitter of the same metric coexisting
  across materials. Caught and reconciled, but only because one agent happened to use the
  canonical file.
- **First CI push failed the repo-wide `ruff format --check`.** The new video-pipeline scripts
  hadn't been run through the repo's format gate before pushing (fixed in follow-up `cb0a9b5`).
  New scripts must clear the repo gate **before** push, not after.

### Root causes (blameless)

| # | Symptom | Root cause | Scope |
|---|---------|-----------|-------|
| RC8 | `ffmpeg` caption step designed against a filter set the local build didn't have; found mid-build | Live-dependency probing (proposal 1) covers APIs/models but was never extended to **local tool/codec capabilities** for media/build pipelines — the same "unprobed dependency" failure mode, different surface | **Generalizable → proposal 7** |
| RC9 | Same metric appeared as two jittered values across published assets until reconciled | No written rule that every audience-facing artifact cites **one named canonical report** and that a regenerated report triggers a full downstream sweep; single-source discipline held by instinct, not by rule | **Generalizable → proposal 6** |
| RC10 | New pipeline scripts failed the repo-wide format gate on first CI push | "The gate is run, not claimed" was applied to the core build but not re-run across **newly added ancillary scripts** before push; already covered by the existing standard — reinforced, no new proposal | **Project-specific (existing standard)** |
| RC4 (closed) | HF write-scope blocked deploy | Confirmed a credential-*scope* gap; resolved once a write-scoped token was supplied — validates proposal 4 | **Resolved** |
| RC6 (practical close) | In-container / image steps couldn't run on the local daemon | Environmental limitation; the CI runner with a built-in scoped token executes the step in a clean room — the practical answer, criterion not weakened | **Resolved via CI** |

### New generalizable lessons (carried to SKILL-UPDATES.md as proposals 6–7)

6. **Canonical-metrics rule** (RC9) → `launch-comms` Gotcha + `solution-rubric` criterion note:
   every audience-facing artifact cites ONE named canonical report; regenerating that report
   triggers a same-change sweep of all downstream assets; jitter variants never coexist.
7. **Probe local tool capabilities too** (RC8) → extend proposal 1's live-probe text in
   `plan-rubric` and `architect` by one sentence: live-dependency probing includes local
   media/build tool capabilities (e.g. `ffmpeg -filters | grep subtitles` before a caption step).

Both are **additive** and **tightening-only**. Per the user's same-session approval of "update
the team skills if needed", proposals 1, 2, 3a, 4, 5, 6, and 7 were **applied on 2026-07-10** to
the live team-skill files; each application is recorded with its target path and backup in
`SKILL-UPDATES.md`. No guardrail was weakened and no quality bar was lowered.
