#!/usr/bin/env bash
# ============================================================================
#  AI Agents Platform - Local Dev Runner for macOS / Linux
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  AI Agents Platform (Prototype)"
echo "========================================"
echo ""

VPY="$SCRIPT_DIR/.venv/bin/python"

if [ ! -f "$VPY" ]; then
    echo "[ERROR] .venv not found - run ./setup.sh first."
    exit 1
fi

# Cleanup background processes on exit (Ctrl+C)
cleanup() {
    echo ""
    echo "Shutting down servers..."
    if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
    if [ -n "${FRONTEND_PID:-}" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    wait 2>/dev/null || true
    echo "All servers stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

echo "Starting Backend Server (port 8000)..."
(
    cd "$SCRIPT_DIR/server"
    exec "$VPY" api.py
) &
BACKEND_PID=$!

echo "Starting Frontend Dev Server..."
(
    cd "$SCRIPT_DIR/frontend"
    exec npm run dev
) &
FRONTEND_PID=$!

echo ""
echo "========================================"
echo "  Both servers are starting!"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5000"
echo "  Admin:    admin / admin123"
echo "========================================"
echo "Press Ctrl+C to stop both servers."
echo ""

# Wait for background processes to run
wait
