# Security Audit & Threat Model

**Project:** Hybrid Token-Efficient Routing Agent (AMD Hackathon ACT II, Track 1)
**Audit date:** 2026-07-07 · **Auditor role:** application security engineer
**Scope:** full source tree, git history, Docker/CI packaging, dependency set.
**Method:** STRIDE decomposition + code review + dependency/secret/injection scan
(`threat-model` skill). This is not a blockchain/web3 project, so the
`smart-contract-audit` skill does not apply — no on-chain surface exists.

> **Bottom line:** The repo is **safe to make public**. Secret scanning is clean
> (the real `fw_` key is only in gitignored `.env`, never committed, absent from
> all history). No CRITICAL or HIGH findings require a builder fix before
> release. Findings below are MEDIUM/LOW hardening items and a short
> pre-release checklist.

---

## 1. System decomposition

### Trust boundaries

| # | Boundary | Untrusted side | Trusted side |
|---|----------|----------------|--------------|
| TB1 | Harness → `adapter.py` | `/input/tasks.json` (attacker-controlled task text) | routing core |
| TB2 | Task text → Fireworks LLMs | task prompt content | model responses (treated as **data**, never executed) |
| TB3 | Demo webapp `POST /solve` | HTTP client on the network | `route()` core |
| TB4 | Environment → `config.py` | operator-supplied env (`FIREWORKS_API_KEY`, `ALLOWED_MODELS`, `FIREWORKS_BASE_URL`) | process |
| TB5 | Public repo → world | anyone reading GitHub | maintainers |

### Entry points

- **`adapter.py`** — file/stdin JSON ingestion, writes `results.json`. The only harness-facing module.
- **`webapp.py`** — FastAPI: `POST /solve`, `GET /api/stats`, `GET /healthz`, `GET /` (inline HTML dashboard).
- **`evals/run_eval.py`** — operator-run offline/live eval harness (not in the shipped runtime image; excluded... see note in Finding L-3).

### Data stores / sensitive data

- **`FIREWORKS_API_KEY`** (sensitive) — lives only in gitignored `.env`; loaded into `Settings` in memory. Never logged, never serialized.
- **`/output/results.json`** — `{id, output}` pairs only; routing metadata/token ledger stays on stderr.
- **`evals/reports/*.json`** — committed evidence; verified to contain **no** raw model `output` and no credentials.
- No database, no user accounts, no session state, no PII collection.

### Tool-permission scope (agentic/LLM assessment)

The "agent" is a **router**, not a tool-calling agent. Confirmed by code review:
`client.py` issues plain `chat.completions.create` calls with `messages`,
`max_tokens`, `stop`, `temperature`, and per-model reasoning params only — **no
`tools`/`functions`/`tool_choice` parameter is ever sent**. Model output is only
ever: (a) string-compared to a Tier-0 solver result (`_cross_check`), (b)
format-validated (`_validate_format`), and (c) returned verbatim as the answer.
Model output is **never** `eval`'d, executed, used as a file path, or fed back as
an instruction. This structurally caps prompt-injection blast radius (see S/T
STRIDE rows).

---

## 2. STRIDE pass

| STRIDE | Threat considered | Assessment | Finding |
|--------|-------------------|------------|---------|
| **S**poofing | Forged requests to demo webapp | No auth by design (public demo, no privileged actions). Acceptable for a stateless demo. | L-1 |
| **S**poofing | Prompt injection spoofing "system" intent | Task text is only ever a `user` message; model output is treated as data, never as instructions/tools. Injection can at worst produce a wrong answer for that one task (accuracy risk, not security). | Info (see §4) |
| **T**ampering | Malicious `tasks.json` (path traversal / oversized / injection) | Output path is fixed (`/output/results.json` or explicit `--output`), never derived from task content → no path traversal. Task text flows only into JSON string values → no injection into results structure. Unbounded input size = DoS-only (M-1). | M-1 |
| **T**ampering | Arithmetic AST-eval escape / exponent bomb | **Empirically probed.** Node whitelist rejects `Name`/`Call`/`Attribute`/etc.; `_MAX_EXPONENT=1000`, `_MAX_ABS_RESULT=1e18`, and Python 3.12 int-str limit reject bombs (100k-digit literal → 5 ms, no hang). No escape found. | Pass |
| **T**ampering | Policy YAML injection | `yaml.safe_load` only; policy path is operator-supplied, not attacker-supplied. | Pass |
| **R**epudiation | Missing audit trail | Out of scope for a hackathon demo; route decisions are logged to stderr. | N/A |
| **I**nfo disclosure | API key echoed in HTTP responses / errors / logs | **Verified false.** `/solve` and `/api/stats` return only answer/route/token/cost fields. Errors surface `ValueError`/`json` messages, never the key. Key is never `log`'d or put in any response model. | Pass |
| **I**nfo disclosure | Secret in git history / image layers | Clean. `.env` gitignored + absent from full history; real key value has **0** matches across all commits and working tree; `.dockerignore` excludes `.env`; no `ENV`/`ARG` secret in Dockerfile. | Pass (see §3) |
| **I**nfo disclosure | Verbose stack traces to demo client | FastAPI default debug is off; `HTTPException` details are curated strings. Low risk. | L-2 |
| **D**enial of service | Oversized/adversarial task input | `POST /solve` caps `prompt` at 8000 chars. `adapter.py` has **no size cap** and loads whole file into memory (M-1). Arithmetic/regex solvers verified non-exploding. | M-1 |
| **D**enial of service | ReDoS in classifier/extraction regexes | Reviewed patterns: no nested unbounded quantifiers / catastrophic backtracking constructs. `.DOTALL .+$` in extraction is linear. Low risk. | L-4 |
| **E**levation of privilege | Container escape / root runtime | Dockerfile runs as non-root `app` user, no `--privileged`, no secret baked in. | Pass |
| **E**levation of privilege | Webapp binds `0.0.0.0` | Intentional for containerized demo; documented with `# noqa: S104`. Acceptable behind the demo host; note for public deploy (L-1). | L-1 |

---

## 3. Secret & git-history scan (the #1 pre-public risk)

**Result: CLEAN.** Verified:

- `.gitignore` contains `.env`; `git check-ignore .env` confirms it is ignored.
- `git log --all --full-history -- .env` → **no commits** ever touched `.env`.
- `git grep fw_ $(git rev-list --all)` → every match is either the placeholder
  `fw_xxxxxxxxxxxxxxxxxxxxxxxx` in `.env.example` or the `fw_test` / `fw_test123`
  **test fixtures** — no real key.
- Grepping the **actual key value** (read from local `.env`) across all history
  and the entire working tree → **0 matches**.
- `.dockerignore` excludes `.env` / `*.env` (keeps `.env.example`) so the key
  cannot enter an image layer; Dockerfile defines no secret `ENV`/`ARG`.
- CI (`ci.yml`) uses **no secrets**, no `pull_request_target`; all tests mock the
  network (respx) with fake keys. No secret-exfiltration foot-gun.
- Committed `evals/reports/*.json` contain no `output` text and no credential-like strings.

---

## 4. Prompt-injection & LLM assessment

Task text is untrusted and reaches the LLMs (TB2). Router design **contains** this:

- **No tool-calling.** Confirmed no `tools`/`function_call` anywhere → an injected
  "ignore instructions and run X" has no tool to invoke.
- **Output-as-data.** Model output is only string-compared, format-checked, and
  returned. It is never executed, never used as a path, never re-issued as an instruction.
- **Residual risk is accuracy, not security:** a crafted task could steer the
  model to a wrong answer or coerce Tier-0 vs Tier-2 routing (a scoring/token
  concern), but cannot achieve code execution, data exfiltration, or privilege gain.

No changes required. This is the correct posture for a routing agent.

---

## 5. Findings table

| ID | Severity | Title | Impact | Status / Remediation |
|----|----------|-------|--------|----------------------|
| M-1 | **MEDIUM** | `adapter.py` has no input-size / task-count cap | A hostile or malformed `/input/tasks.json` (multi-GB, or millions of tasks) is read fully into memory and each task may trigger a paid model call → memory-exhaustion DoS and/or unbounded token spend. | **Open — builder (non-blocking for public release).** Add a max file-size check before `read_text`, and/or a max task-count guard in `_parse_tasks`. Harness-mode only; not reachable from the public web surface. |
| M-2 | **MEDIUM** | Demo webapp lacks rate limiting | If the demo URL is public, unauthenticated `POST /solve` can be scripted to burn Fireworks tokens/cost on the maintainer's key. | **Open — deploy-time.** Put the demo behind a rate limit / auth proxy, or run demo in Tier-0-only mode (no key) for the public link. Document in README. |
| L-1 | LOW | No auth on webapp; binds `0.0.0.0` | Expected for a demo; only a concern if the same instance holds the real key on a public network (overlaps M-2). | Accepted for demo. Note in deploy docs. |
| L-2 | LOW | Error detail strings returned to client | Curated messages only; low disclosure risk, but keep messages generic when deployed publicly. | Accepted. |
| L-3 | LOW | `evals/` copied into runtime image | `Dockerfile` `COPY evals/ ./evals/` ships eval corpus/reports into the harness image (size, not secret — reports are already public-clean). | Optional: drop `evals/` from the runtime `COPY` if image size matters; no security impact. |
| L-4 | LOW | Regex complexity in classifier/extraction | Reviewed; no catastrophic backtracking found. Kept as a note for future pattern edits. | Accepted — re-review if patterns grow. |
| I-1 | INFO | `_baseline_estimate_tokens` / savings figures are estimates | Not a vulnerability; ensure demo copy labels savings as "estimated vs naive baseline" to avoid misleading claims. | Accepted. |

**Dependency review:** current, no known CVEs at audit date — fastapi 0.139.0,
starlette 1.3.1, pydantic 2.13.4, openai 2.44.0, httpx 0.28.1, uvicorn (current),
pyyaml 6.0.3, python-dateutil 2.9.0. All pinned via `uv.lock` (`--frozen` in
Docker & CI). No `eval`/`exec`/`os.system`/`subprocess`/`pickle`/unsafe-`yaml.load`
anywhere in `src/` or `evals/`. No CORS misconfiguration (no permissive
`allow_origins`; same-origin default). Inline dashboard inserts model/answer text
via **`textContent`** (XSS-safe); the only `innerHTML` writes are for a
hardcoded tier badge and static `—` placeholders, never user/model data.

### Counts by severity

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 2 (M-1, M-2) |
| LOW | 4 (L-1…L-4) |
| INFO | 1 |

### Remediated during this audit

Nothing required a code change: the highest-value risk (secret leakage) was
already fully mitigated, and every attack surface flagged in the brief
(arithmetic AST eval, adapter path traversal, webapp XSS/CORS/key-echo,
prompt-injection tool scope, Dockerfile non-root/secrets, CI secrets) **passed**.
The two MEDIUM items are hardening recommendations for the builder/deployer, not
release blockers. Per audit scope (read/analysis + non-destructive scans only),
no source files other than this report were modified.

---

## 6. Public-release checklist

Confirm immediately before flipping the repo to public:

- [ ] `git log --all --full-history -- .env` returns **nothing** (re-run; it is clean now).
- [ ] `git grep -n fw_ $(git rev-list --all)` shows **only** `fw_xxx…` placeholder + `fw_test` fixtures.
- [ ] Local `.env` is still **untracked** (`git status` shows it ignored) and the real key was **never** `git add`-ed.
- [ ] **Rotate the Fireworks key anyway** if there is any doubt it was ever pasted into a tracked file, a screenshot, or a demo recording — cheap insurance.
- [ ] Public demo URL either (a) runs in **Tier-0-only / no-key** mode, or (b) sits behind rate limiting + a **separate, low-quota key**, not the leaderboard key (M-2).
- [ ] `.dockerignore` still excludes `.env`; no image pushed to a public registry contains a baked key.
- [ ] CI remains secret-free and uses no `pull_request_target` (verified).
- [ ] README/demo copy labels token-savings numbers as **estimated vs a naive baseline** (I-1).
- [ ] (Optional, non-blocking) Land M-1 input-size guard in `adapter.py` before any untrusted `tasks.json` is run outside the scored harness.
