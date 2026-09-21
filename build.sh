#!/bin/bash
set -euo pipefail

echo "=== Building frontend ==="
cd frontend

if [ ! -d "node_modules" ]; then
  echo "Installing npm packages..."
  npm install
fi

echo "Running frontend build..."
npm run build

cd ..

if [ -d "frontend/dist" ] && [ -f "frontend/dist/index.html" ]; then
  echo "=== Frontend dist ready ==="
else
  echo "ERROR: frontend/dist not found!"
  exit 1
fi

echo "=== Installing Playwright browsers ==="
python -m playwright install chromium

echo "=== Build complete ==="
