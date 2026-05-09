#!/bin/bash
# Start both backend and frontend dev servers.
# Usage: ./start.sh

cd "$(dirname "$0")"

if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "WARN: ANTHROPIC_API_KEY is not set — document extraction/classifier calls will fail until you export it or add .env."
fi

if [ ! -d ".venv" ]; then
    echo "Creating .venv ..."
    python3 -m venv .venv
    .venv/bin/python -m pip install -q --upgrade pip
    .venv/bin/python -m pip install -q -r requirements.txt
fi

# Default 8010 — change if busy: PORT=8020 ./start.sh
BACKEND_PORT="${PORT:-${BACKEND_PORT:-8010}}"

echo "Starting backend on http://localhost:${BACKEND_PORT} ..."
.venv/bin/python -m uvicorn main:app --reload --host 127.0.0.1 --port "${BACKEND_PORT}" &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:8080 ..."
cd src/frontend && VITE_BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}" npm run dev &
FRONTEND_PID=$!

echo ""
echo "Backend:  http://localhost:${BACKEND_PORT}"
echo "Frontend: http://localhost:8080  (VITE_BACKEND_URL=http://127.0.0.1:${BACKEND_PORT})"
echo ""
echo "Press Ctrl+C to stop both servers."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" INT TERM
wait
