---
title: AMD Routing Agent Demo
emoji: 🧭
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Token-efficient tiered LLM routing cascade — live demo
---

# AMD Routing Agent — Live Demo

This Space runs the judge-facing dashboard (`routing_agent.webapp`) for the
Hybrid Token-Efficient Routing Agent built for AMD Hackathon ACT II, Track 1.
Submit a prompt and watch it get routed through the Tier 0 (deterministic
solver, zero tokens) → Tier 1 (cheapest adequate model) → Tier 2 (escalation)
cascade, with live token/cost/savings reporting.

**Main repository (source of truth, full README, PLAN, SECURITY audit):**
https://github.com/SebAustin/amd-routing-agent

**This file is packaging only.** See `/Users/sebastienhenry/Documents/Hackathons/AMD Dev Hackathon/DEPLOYMENT.md`
in the main repo for how this Space is assembled and deployed.

---

## How the orchestrator assembles this Space repo

This `spaces/README.md` and `Dockerfile.spaces` live in the main GitHub repo
but are **not** used as-is by Hugging Face — the Space is a separate git
repo that the orchestrator assembles from selected files out of the main
repo. This keeps one source of truth (GitHub) while producing a
Spaces-compatible layout (HF requires `README.md` + `Dockerfile` at the
Space repo root).

Assembly steps (performed by the orchestrator, not by this file):

1. Create/clone the Space repo `SebAustin/amd-routing-agent-demo`.
2. Copy `Dockerfile.spaces` from the main repo root → Space repo root,
   **renamed to `Dockerfile`**.
3. Copy `spaces/README.md` (this file) → Space repo root, **renamed to
   `README.md`** (the YAML front-matter above is what HF parses for the
   Space card — title/emoji/sdk/app_port).
4. Copy `src/` (the `routing_agent` package) → Space repo `src/`.
5. Copy `evals/policies/` (routing policy YAML only — **not** the full
   `evals/evalset/` corpus or `evals/reports/`, to keep the Space image
   lean) → Space repo `evals/policies/`.
6. Copy `pyproject.toml`, `uv.lock`, and the main repo's `README.md` (the
   package's own readme, required by hatchling at build time — see
   `Dockerfile.spaces` comments) → Space repo root.
7. Set Space secrets (see main repo `DEPLOYMENT.md` for the exact gated
   command — this step is **never** performed by copying a file; it is a
   `hf` CLI / web UI action against the Space's own secret store).
8. Push the assembled Space repo to the Hugging Face remote.

The harness/scoring Dockerfile at the main repo root is untouched by any of
this — it stays the default `docker run` entry point for the scoring
harness (`ENTRYPOINT ["python", "-m", "routing_agent.adapter"]`).
`Dockerfile.spaces` is only ever used for the Space variant described above.
