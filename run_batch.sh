#!/usr/bin/env bash
# Run the AnaSafe batch validator across cases/ (defaults).
# Usage: ./run_batch.sh [folder] [--threshold 70] [--json out.json]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

CASES="${1:-cases}"
shift || true

exec .venv/bin/python src/backend/validation/batch_runner.py "$CASES" "$@"
