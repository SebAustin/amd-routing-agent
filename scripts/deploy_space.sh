#!/usr/bin/env bash
# One-command gated deploy of the demo dashboard to a Hugging Face Docker Space.
#
# Requirements:
#   - A WRITE-scoped Hugging Face token (https://huggingface.co/settings/tokens)
#     exported as HF_TOKEN (the default keyring token on this machine is read-only).
#   - The real key in ./.env (FIREWORKS_API_KEY) — read locally, sent only to the
#     Space's private secret store, never printed.
#
# Usage:
#   HF_TOKEN=hf_xxx ./scripts/deploy_space.sh [--dry-run]
#
# --dry-run assembles the Space working tree and prints the plan without any
# network call — safe to run anytime.

set -euo pipefail

SPACE_ID="${SPACE_ID:-SebAustin/amd-routing-agent-demo}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)/space"
DRY_RUN="${1:-}"

# --- Assemble the Space working tree (per spaces/README.md) -------------------
mkdir -p "$STAGE"
cp "$REPO_ROOT/Dockerfile.spaces" "$STAGE/Dockerfile"
cp "$REPO_ROOT/spaces/README.md" "$STAGE/README.md"
cp "$REPO_ROOT/pyproject.toml" "$REPO_ROOT/uv.lock" "$STAGE/"
cp -R "$REPO_ROOT/src" "$STAGE/src"
mkdir -p "$STAGE/evals"
cp -R "$REPO_ROOT/evals/policies" "$STAGE/evals/policies"
cp "$REPO_ROOT/evals/graders.py" "$STAGE/evals/graders.py" 2>/dev/null || true
# hatchling needs a readme; the Space README (front-matter) satisfies pyproject.
find "$STAGE" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

echo "Assembled Space tree at $STAGE:"
(cd "$STAGE" && find . -maxdepth 2 -type f | sort | head -30)

if [ "$DRY_RUN" = "--dry-run" ]; then
  echo "[dry-run] Would push to https://huggingface.co/spaces/$SPACE_ID and set:"
  echo "  secret   FIREWORKS_API_KEY   (from .env, not printed)"
  echo "  variable FIREWORKS_BASE_URL, ALLOWED_MODELS, RATE_LIMIT_PER_MIN=10, DEMO_DAILY_BUDGET_USD=1.00"
  exit 0
fi

: "${HF_TOKEN:?Set HF_TOKEN to a WRITE-scoped Hugging Face token}"
FIREWORKS_API_KEY="$(grep '^FIREWORKS_API_KEY=' "$REPO_ROOT/.env" | cut -d= -f2-)"
[ -n "$FIREWORKS_API_KEY" ] || { echo "FIREWORKS_API_KEY missing from .env" >&2; exit 1; }
export FIREWORKS_API_KEY HF_TOKEN

python3 - "$SPACE_ID" "$STAGE" <<'PY'
import os, sys
from huggingface_hub import HfApi

space_id, stage = sys.argv[1], sys.argv[2]
api = HfApi(token=os.environ["HF_TOKEN"])
api.create_repo(space_id, repo_type="space", space_sdk="docker", exist_ok=True)
api.add_space_secret(space_id, "FIREWORKS_API_KEY", os.environ["FIREWORKS_API_KEY"])
api.add_space_variable(space_id, "FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
api.add_space_variable(
    space_id,
    "ALLOWED_MODELS",
    ",".join(
        f"accounts/fireworks/models/{m}"
        for m in ["gpt-oss-20b", "gpt-oss-120b", "deepseek-v4-flash", "deepseek-v4-pro", "glm-5p1"]
    ),
)
api.add_space_variable(space_id, "RATE_LIMIT_PER_MIN", "10")
api.add_space_variable(space_id, "DEMO_DAILY_BUDGET_USD", "1.00")
api.upload_folder(folder_path=stage, repo_id=space_id, repo_type="space", commit_message="deploy: routing-agent demo dashboard")
print(f"Deployed: https://huggingface.co/spaces/{space_id}")
print(f"Live URL (after build): https://{space_id.replace('/', '-').lower()}.hf.space")
PY
