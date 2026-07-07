# routing-agent

Hybrid token-efficient routing agent for the AMD Developer Cloud Hackathon,
ACT II Track 1. Completes a fixed set of tasks against Fireworks AI models
while minimizing total tokens spent, via a tiered cascade:

```
task -> classifier (0 tokens)
     -> Tier 0: deterministic solvers (0 tokens: arithmetic, dates, strings,
        units, extraction)
     -> Tier 1: cheapest adequate allowed model, confidence-gated
     -> Tier 2: single escalation to the strongest allowed model
```

See `PLAN.md` for the full design and `ASSUMPTIONS.md` for open questions
about the scoring harness.

## Setup

```bash
uv sync --group dev
cp .env.example .env   # fill in FIREWORKS_API_KEY and ALLOWED_MODELS
```

## Running

```bash
# Reads /input/tasks.json, writes /output/results.json
uv run python -m routing_agent

# Or explicit paths:
uv run python -m routing_agent.adapter --input tasks.json --output results.json
```

## Development

```bash
uv run ruff format .
uv run ruff check .
uv run pytest -q
```

## Layout

- `src/routing_agent/` — the package (config, models, registry, client,
  classifier, solvers/, prompts, router, adapter).
- `evals/` — eval task sets, policies, and the eval runner (in progress).
- `tests/` — unit tests, no network (HTTP calls mocked with `respx`).
