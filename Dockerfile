# syntax=docker/dockerfile:1
# Routing agent image: harness mode by default (adapter.py reads
# /input/tasks.json -> /output/results.json). Demo mode is a documented
# override (see the `docker run ... python -m routing_agent.webapp` command
# below and in docker-compose.yml's `demo` service).
#
# Single stage, python:3.12-slim base, uv installed from its official
# distroless image (binary-only copy, no extra layers). Only the `main`
# dependency group is installed (no dev/test tooling) to keep the image
# small — target <500MB, no torch/CUDA anywhere in the dependency tree.

FROM python:3.12-slim AS base

# Copy the uv/uvx binaries from the official distroless uv image instead of
# installing via pip or curl|sh — smaller, pinned, and avoids a build-time
# network fetch script.
COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first (layer caching): only the `main` (default)
# dependency group, never `dev` — no pytest/ruff/respx in the shipped image.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Now copy source and install the project itself. README.md is required by
# hatchling (pyproject `readme` field) to build the project wheel.
COPY README.md ./
COPY src/ ./src/
COPY evals/ ./evals/
RUN uv sync --frozen --no-dev

# Non-root user; harness mounts /input and /output as volumes, so the
# runtime user only needs write access to /output (created here so a
# read-only host mount of /input still works).
RUN groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /input /output \
    && chown -R app:app /app /input /output

USER app

# Harness-facing default: adapter.py reads /input/tasks.json, writes
# /output/results.json. Override with:
#   docker run -p 8000:8000 <img> python -m routing_agent.webapp
# to run the demo dashboard instead.
ENTRYPOINT ["python", "-m", "routing_agent.adapter"]
