# SKILL-UPDATES — proposals awaiting explicit approval

Source retro: `POSTMORTEM.md` (AMD Hackathon ACT II, Track 1, 2026-07-07).

**Approval gate (mandatory).** Nothing below is applied, merged, or created live without the
user's explicit, per-item approval. Approved items land **only on a feature branch** for review;
merging to the shared marketplace / default branch is a separate human (admin) decision.

**All proposals are additive and tightening-only.** None weakens or removes a guardrail
(security, secrets, money/deploy gates) and none lowers a quality bar (rubric thresholds, the
SOLID gate, iteration discipline). They add checks and record encountered failure modes; they
never relax.

Reply with the numbers you approve (e.g. "apply 1, 3, 5"). Unapproved items are left as-is.

---

## 1. Plan-rubric + architect: require live-environment probing before the plan freezes

**Motivation (evidence).** Probing the real Fireworks key on Day 1 surfaced four facts that
would each have been mid-build surprises: Gemma is NOT serverless despite the partner prize;
unlisted models are callable (`/models` is not authoritative); a reasoning-token trap; ~82-token
per-model prompt overhead (PLAN.md §2; ASSUMPTIONS.md #6, #7). The logprobs probe *materially
changed the design* — format-validation became the PRIMARY confidence gate (PLAN.md r2). This
happened by good instinct, not by process (POSTMORTEM RC1).

**Target file A:** `~/.claude/skills/plan-rubric/SKILL.md`
Add one row to the criteria table (renumbering weights is a human decision; suggested as an
addition to Feasibility guidance rather than a re-weight to avoid touching thresholds):

Append to the criterion 3 "Feasibility" cell, or add as a sub-bullet under the table:
```
- Feasibility "5" also requires: any external environment the plan depends on (API keys,
  model availability, harness contract, third-party service scopes) has been **probed live**
  where cheap to do so, and the probe's findings are reflected in the design — not assumed.
  An unprobed assumption about a live dependency that is cheaply checkable caps Feasibility at 3.
```

**Target file B:** `~/.claude/agents/architect.md`
Add a bullet under "Cover in `PLAN.md`":
```
- **Live-environment probe (when a live dependency exists and is cheap to check)**: before
  freezing the design, probe the real API/model/harness (a few cheap calls) and record the
  findings — available models, response shape, token/overhead quirks, credential scope. Let
  the findings drive the design; note them in a "Live environment facts" section.
```

**Why it can't lower a bar:** it only *adds* a requirement to reach a "5" and adds a design step.

---

## 2. agency-orchestration: document the parallel-builder protocol

**Motivation (evidence).** Two build waves ran in parallel (core + evalset; then eval-tuning +
webapp/Docker) and worked, with only one trivial cross-boundary lint leak in `evals/graders.py`
(POSTMORTEM §2, §4). They worked *because* file boundaries and a single git owner were set up
ad hoc — the manual doesn't document the protocol, so the next run may not repeat the discipline
(RC2).

**Target file:** `~/.claude/skills/agency-orchestration/SKILL.md`
Add a subsection under "## Workflow" (after step 3, "Build & verify loop"):
```
### Parallel builders (optional, when milestones are independent)
When two builders can work at once (e.g. core package + eval set; webapp + tuning), the
orchestrator MUST set these rules up front, before dispatch:
- **Disjoint file boundaries.** Each builder owns an explicit, non-overlapping set of paths.
  Name the owner of any shared/interface file (e.g. a grader or schema both touch) — exactly
  one builder edits it; the other consumes it.
- **Single git owner.** Exactly one builder (or the orchestrator) stages and commits, with
  explicit paths (never `git add -A`). Parallel builders hand off diffs; they do not commit
  concurrently.
- **Boundary lint sweep.** After a parallel wave, the git owner runs the full lint gate across
  the merged tree — cross-boundary leaks (a file one builder created that the other's lint
  config governs) are caught here, not later.
Only parallelize genuinely independent milestones; anything with a data/interface dependency
stays sequential.
```

**Why it can't lower a bar:** additive orchestration guidance; it *tightens* the existing
"explicit-paths / no `git add -A`" guardrail by adding a single-git-owner rule for parallelism.

---

## 3. doc-writer + orchestration: shell-less roles must not own their own verification gate

**Motivation (evidence).** `doc-writer`'s prompt says "verify commands and paths exist," but its
tools are `Read, Write, Edit, Grep, Glob` — **no Bash** — so it cannot run the commands it
documents. It also inspected git via Glob and **wrongly concluded "no .git"** on a repo that is
in fact a git repo (POSTMORTEM §4, RC3). The orchestrator ran the gate instead.

Two options; **3a is preferred** (keeps the role self-sufficient), 3b is the fallback if adding
Bash to doc-writer is undesirable.

**Option 3a — Target file:** `~/.claude/agents/doc-writer.md`
Add `Bash` to the `tools:` frontmatter and add a bullet:
```
tools: Read, Write, Edit, Bash, Grep, Glob
```
```
- **Verify before you document.** Actually run each command and check each path you put in the
  docs (a quickstart that doesn't run is a bug). Detect the VCS with `git rev-parse` /
  `git status`, not by globbing for a `.git` directory — a worktree or nested checkout will
  fool a Glob-only check.
```

**Option 3b — Target file:** `~/.claude/skills/agency-orchestration/SKILL.md`
If doc-writer stays shell-less, add to Workflow step 5 (Docs):
```
Shell-less roles (e.g. doc-writer without Bash) cannot verify the commands/paths they write.
For these, the **orchestrator owns the verification gate**: run every documented command and
path check yourself and feed corrections back before docs are accepted. Never accept a
"verified" claim from a role that lacks the tool to verify.
```

**Why it can't lower a bar:** 3a gives the role the tool to *meet* its existing verify
requirement; 3b assigns the gate to a role that can run it. Either way verification coverage
increases.

---

## 4. requirements-analyst + plan-rubric: preflight credential *scope* at intake

**Motivation (evidence).** The approved HF Space deploy was fully built, then blocked at the
last mile because the provided HF token was **read-only** (POSTMORTEM §4, RC4;
ACCEPTANCE.md Deferred #4). Credential *presence* is checked (ASSUMPTIONS.md #12), but the
*scope* required for each planned external service was not checked until deploy time.

**Target file A:** `~/.claude/agents/requirements-analyst.md`
Add a bullet under "Do:":
```
- **Credential-scope preflight.** For every external service the project will call or deploy to
  (model APIs, registries, hosting like HF Spaces / Fly, cloud accounts), record in
  ASSUMPTIONS.md: which credential is needed, what *scope/permission* it must have (read vs
  write vs deploy), and how to verify that scope now. A capability required at deploy time
  (e.g. a write-scoped token) is a Day-1 assumption to validate, not a deploy-day surprise.
```

**Target file B:** `~/.claude/skills/plan-rubric/SKILL.md`
Add to criterion 5 "Completeness" guidance (as a sub-bullet):
```
- Completeness includes credential scope: every planned external service names the credential
  and the exact scope it needs (read/write/deploy), with a verify-now step. An external
  dependency whose required credential scope is unspecified is a hand-waved failure mode.
```

**Why it can't lower a bar:** adds an intake step and tightens the completeness definition.

---

## 5. solution-rubric + architect: honest-baseline principle for comparative metrics

**Motivation (evidence).** SC2 is a comparative claim ("≥60% token reduction vs baseline"). The
eval-tuning agent *chose* to make the baseline fairer (`apply_reasoning_profile=False`,
ADR-0004), which roughly halved the reported win but kept it honest; the team then reported SC2
as an honest FAIL (ACCEPTANCE.md; evals/README.md §5). This honesty rested on an individual
agent's judgment, not a written principle (POSTMORTEM RC5). The eval README even declines to
call two same-policy runs a real before/after — the right instinct, worth codifying.

**Target file A:** `~/.claude/skills/solution-rubric/SKILL.md`
Add to criterion 1 "Criteria met" guidance (as a sub-bullet under the table, or appended to the
criterion 1 cell):
```
- Any comparative or headline metric (X% faster/cheaper/better "vs baseline") is judged against
  an **honest baseline**: the baseline must reflect a genuinely naive/default alternative, not
  one handicapped to flatter the result, and must be described so a skeptic could reproduce it.
  A favorable-looking number built on an unfair or unstated baseline does NOT count toward
  "criteria met" — report the honest figure even when it misses the target.
```

**Target file B:** `~/.claude/agents/architect.md`
Add a bullet under "Cover in `PLAN.md`":
```
- **Baselines for comparative success criteria.** Any SC phrased as "vs baseline" must define
  the baseline explicitly and fairly (a real naive/default alternative, reasoning/tuning
  disabled), and state how it is measured, so the comparison can't drift into self-flattery.
```

**Why it can't lower a bar:** it *raises* the bar for what counts as a met comparative criterion
and forbids flattering baselines. It cannot be used to inflate a score.

---

## Not proposed (considered and rejected)

- **A new "environment-prober" agent.** Rejected — this is a *step* the architect/orchestrator
  should own (proposal 1), not a standalone role. Adding an agent for a one-call probe would
  bloat the roster and overlap the architect. Prefer improving the existing role.
- **A new "deploy-credential" agent.** Rejected — credential-scope preflight belongs in
  requirements-analyst intake (proposal 4) and the fde deploy gate, both existing roles.
- **Relaxing SC4's in-container run requirement** because the local Docker daemon was down.
  Rejected on principle — never lower a bar. The gap is environmental (POSTMORTEM RC6); the fix
  is to run the image where a daemon exists, not to weaken the criterion.
