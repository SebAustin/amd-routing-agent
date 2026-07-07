# ASSUMPTIONS

Logged per the agency workflow; each carries its mitigation if wrong.

1. **Harness contract**: Track 1 scoring harness follows Track 2's published pattern — Docker image reading `/input/tasks.json`, writing `/output/results.json`. *If wrong*: only `adapter.py` changes (Day-4 buffer reserved).
2. **tasks.json schema**: a JSON array of objects with at least `id` and a text field (`prompt`/`input`/`question` — adapter accepts any of these); results keyed by `id` with an `output`/`answer` string. *If wrong*: adapter remap.
3. **ALLOWED_MODELS format**: comma-separated Fireworks model ids in an env var. *If wrong*: config parser handles JSON arrays and bare names too.
4. **Accuracy threshold**: unknown; assume ≥ 90% and tune conservatively (prefer accuracy over token savings at the margin). *If wrong*: policy YAML flips the operating point in one line.
5. **Scoring metric**: raw total tokens (not price-weighted). TokenLedger tracks both. *If wrong*: objective flips in config.
6. **Gemma access**: not serverless on this account today (probed Jul 7 — all variants NOT_FOUND); assume the hackathon env may expose Gemma via its own `FIREWORKS_BASE_URL`. Registry prefers `gemma*` at equal tier automatically. *If never available*: Gemma-aware routing is still demonstrated in code/tests/README for the partner prize narrative.
7. **Callable model set today**: `gpt-oss-20b`, `gpt-oss-120b`, `deepseek-v4-flash`, `deepseek-v4-pro`, `glm-5p1`, `glm-5p2`, `kimi-k2p5`, `kimi-k2p6` (probed live). Unlisted ids may still be callable — startup probe, don't trust `/models` alone.
8. **Deadline**: submission due July 11, 2026 (from lablab event page research); Event Schedule tab is authoritative.
9. **Prices**: third-party approximations (gpt-oss-20b ≈ $0.07/$0.30 per M; tiers $0.10–0.90/M) pending re-verification; used only for relative ranking, which is robust to small errors.
10. **Demo hosting**: Hugging Face Spaces (Docker Space) acceptable as the "Application URL". *If not*: Fly.io backup.
11. **Language/stack**: Python 3.12 + uv; no torch in the scored image (size + startup).
12. **The provided API key** stays in gitignored `.env` only; CI runs fully mocked. The key was shared in chat — recommend rotating it after the hackathon.
13. **Eval task-type mix** (arithmetic/dates/strings/classification/extraction/QA/code/summarization, roughly uniform) is a guess at the real harness distribution. Route-distribution and SC2/SC3 numbers must be re-validated against any sample tasks the organizers publish.
