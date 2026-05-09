#!/usr/bin/env bash
# Start the FastAPI backend from repo root with a sane default environment.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -d .venv ]; then
  echo "Creating .venv ..."
  python3 -m venv .venv
fi

echo "Installing/updating Python dependencies (requires network once) ..."
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

BACKEND_PORT="${PORT:-${BACKEND_PORT:-8010}}"
echo "Starting API at http://127.0.0.1:${BACKEND_PORT}"
echo "(Set PORT=8011 if this port is busy. ANTHROPIC_API_KEY required for Claude-based extraction.)"
exec .venv/bin/python -m uvicorn main:app --reload --host 127.0.0.1 --port "${BACKEND_PORT}"
