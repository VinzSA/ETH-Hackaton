#!/bin/bash
# Start both backend and frontend dev servers.
# Usage: ./start.sh

cd "$(dirname "$0")"

if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set. Add it to .env"
    exit 1
fi

echo "Starting backend on http://localhost:8000 ..."
er-preop-brief/.venv/bin/uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:5173 ..."
cd src/frontend && npm run dev &
FRONTEND_PID=$!

echo ""
echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop both servers."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" INT TERM
wait
