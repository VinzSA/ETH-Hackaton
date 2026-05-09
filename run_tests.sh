#!/bin/bash
set -e

cd "$(dirname "$0")"

# Load API key from .env if not already set in the shell
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set."
    echo "Create a .env file in this folder with:"
    echo "  ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi

PYTHON=er-preop-brief/.venv/bin/python

echo "========================================"
echo " TEST 1: Synthetic clinical notes"
echo "========================================"
PYTHONPATH=. $PYTHON tests/test_pipeline.py

echo ""
echo "========================================"
echo " TEST 2: Real MT Samples data"
echo "========================================"
PYTHONPATH=. $PYTHON tests/run_mtsamples.py
