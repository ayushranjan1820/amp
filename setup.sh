#!/usr/bin/env bash
# ============================================================================
#  AI Agents Platform - one-shot setup for macOS / Linux
#
#  Installs everything needed to run the app locally:
#    - Python virtual environment at .venv + all backend dependencies
#    - Playwright Chromium (Browser agent)
#    - server/.env bootstrapped from server/.env.example
#    - Frontend npm packages (frontend/node_modules)
#    - Root npm packages
#
#  Usage:
#    ./setup.sh                    default install
#    ./setup.sh --full             also install heavy optional extras
#                                  (sentence-transformers / torch, ~2 GB)
#    ./setup.sh --skip-browsers    skip the Playwright Chromium download
#    ./setup.sh --skip-node        skip all npm installs
#    ./setup.sh --help             show this help
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FULL=0
SKIP_BROWSERS=0
SKIP_NODE=0

usage() {
    cat <<EOF

  ./setup.sh [--full] [--skip-browsers] [--skip-node]

    --full            also install heavy optional extras from
                      server/requirements.txt (sentence-transformers/torch)
    --skip-browsers   do not download Playwright Chromium
    --skip-node       do not run any npm install
    -h, --help        show this help

EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --full)
            FULL=1
            shift
            ;;
        --skip-browsers)
            SKIP_BROWSERS=1
            shift
            ;;
        --skip-node)
            SKIP_NODE=1
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "[WARN] Unknown option: $1"
            shift
            ;;
    esac
done

echo "============================================================"
echo "  AI Agents Platform - Setup"
echo "  $(pwd)"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# [1/8] Check prerequisites
# ---------------------------------------------------------------------------
echo "[1/8] Checking prerequisites..."

# Search for suitable python executable (>=3.11 and <3.14)
PYTHON_CANDIDATES=("python3" "python" "python3.13" "python3.12" "python3.11" "/opt/homebrew/bin/python3.13" "/opt/homebrew/bin/python3.12" "/opt/homebrew/bin/python3.11" "/usr/local/bin/python3.13" "/usr/local/bin/python3.12" "/usr/local/bin/python3.11")
CHOSEN_PYTHON=""

for cand in "${PYTHON_CANDIDATES[@]}"; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" 2>/dev/null; then
            CHOSEN_PYTHON="$cand"
            break
        fi
    fi
done

if [ -z "$CHOSEN_PYTHON" ]; then
    echo "  [ERROR] Python >=3.11 and <3.14 was not found on PATH."
    echo "          Please install Python 3.11, 3.12 or 3.13."
    echo "          On macOS with Homebrew: brew install python@3.12"
    exit 1
fi

PYVER="$("$CHOSEN_PYTHON" -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')")"
echo "  OK  Python $PYVER ($CHOSEN_PYTHON)"

if [ "$SKIP_NODE" -eq 0 ]; then
    if ! command -v npm >/dev/null 2>&1 || ! command -v node >/dev/null 2>&1; then
        echo "  [ERROR] Node.js / npm was not found on PATH."
        echo "          Install Node.js 20 or newer from https://nodejs.org/ or using nvm / brew."
        exit 1
    fi
    NODEVER="$(node -v)"
    echo "  OK  Node $NODEVER"
else
    echo "  --  Node checks skipped"
fi
echo ""

# ---------------------------------------------------------------------------
# [2/8] Python virtual environment
# ---------------------------------------------------------------------------
echo "[2/8] Preparing Python virtual environment (.venv)..."
VPY="$SCRIPT_DIR/.venv/bin/python"

if [ -f "$VPY" ]; then
    echo "  Reusing existing .venv"
else
    "$CHOSEN_PYTHON" -m venv .venv
    echo "  Created .venv"
fi

if [ ! -f "$VPY" ]; then
    echo "  [ERROR] .venv/bin/python is missing - the venv looks broken."
    echo "          Delete the .venv folder and run ./setup.sh again."
    exit 1
fi
echo ""

# ---------------------------------------------------------------------------
# [3/8] Base packaging tools
# ---------------------------------------------------------------------------
echo "[3/8] Upgrading pip / setuptools / wheel..."
"$VPY" -m pip install --upgrade pip setuptools wheel
echo ""

# ---------------------------------------------------------------------------
# [4/8] Backend dependencies (pyproject.toml)
# ---------------------------------------------------------------------------
echo "[4/8] Installing backend dependencies from pyproject.toml..."
echo "      (this might take several minutes on a cold cache)"

DEPFILE="$(mktemp /tmp/agents_deps_XXXXXX.txt)"
"$VPY" -c "import tomllib, pathlib, sys; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); pathlib.Path(sys.argv[1]).write_text('\n'.join(d['project']['dependencies']), encoding='utf-8')" "$DEPFILE"

"$VPY" -m pip install -r "$DEPFILE"
rm -f "$DEPFILE"

# pymysql is needed by SQL DB agent
"$VPY" -m pip install "pymysql>=1.1.0"

if [ "$FULL" -eq 1 ]; then
    echo ""
    echo "  --full requested: installing optional extras from server/requirements.txt"
    echo "  (includes sentence-transformers + torch, this downloads ~2 GB)"
    "$VPY" -m pip install -r server/requirements.txt
fi
echo "  OK  Backend dependencies installed"
echo ""

# ---------------------------------------------------------------------------
# [5/8] Playwright browser
# ---------------------------------------------------------------------------
echo "[5/8] Playwright Chromium (Browser agent)..."
if [ "$SKIP_BROWSERS" -eq 1 ]; then
    echo "  --  Skipped (--skip-browsers). Run this later from the project root:"
    echo "      .venv/bin/python -m playwright install chromium"
else
    if "$VPY" -m playwright install chromium; then
        echo "  OK  Chromium installed"
    else
        echo "  [WARN] Chromium download failed. The app still runs; only the Browser agent is affected."
        echo "         Retry later with: .venv/bin/python -m playwright install chromium"
    fi
fi
echo ""

# ---------------------------------------------------------------------------
# [6/8] Environment files
# ---------------------------------------------------------------------------
echo "[6/8] Environment files..."
ENV_CREATED=0
if [ -f "server/.env" ]; then
    echo "  OK  server/.env already exists - left untouched"
else
    if [ -f "server/.env.example" ]; then
        cp "server/.env.example" "server/.env"
        ENV_CREATED=1
        echo "  Created server/.env from server/.env.example"
    else
        echo "  [WARN] server/.env.example not found - create server/.env manually."
    fi
fi
echo ""

# ---------------------------------------------------------------------------
# [7/8] Frontend packages
# ---------------------------------------------------------------------------
echo "[7/8] Frontend npm packages..."
if [ "$SKIP_NODE" -eq 1 ]; then
    echo "  --  Skipped (--skip-node)"
else
    (
        cd frontend
        if [ -f "package-lock.json" ]; then
            npm ci || {
                echo "  [WARN] 'npm ci' failed - falling back to 'npm install'"
                npm install
            }
        else
            npm install
        fi
    )
    echo "  OK  frontend/node_modules ready"
fi
echo ""

# ---------------------------------------------------------------------------
# [8/8] Root packages + verification
# ---------------------------------------------------------------------------
echo "[8/8] Root npm packages and verification..."
if [ "$SKIP_NODE" -eq 1 ]; then
    echo "  --  Root npm install skipped (--skip-node)"
else
    npm install || echo "  [WARN] Root 'npm install' failed. The frontend and backend still work."
    echo "  OK  Root node_modules ready"
fi

"$VPY" -c "import fastapi, uvicorn, pydantic, langchain_core, pymongo, sqlalchemy" >/dev/null 2>&1
echo "  OK  Core backend imports verified"
echo ""

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Setup complete"
echo "============================================================"
echo ""
if [ "$ENV_CREATED" -eq 1 ]; then
    echo "  NEXT STEP - server/.env was created from the template and still"
    echo "  holds placeholder values. Fill in at least:"
    echo ""
    echo "    MONGODB_URI            MongoDB connection string"
    echo "    EXTERNAL_DATABASE_URL  PostgreSQL connection string"
    echo "    SESSION_SECRET         run: .venv/bin/python -c 'import secrets;print(secrets.token_hex(32))'"
    echo "    ANTHROPIC_API_KEY      and/or OPENAI_API_KEY"
    echo ""
fi
echo "  Start the app with:   ./start.sh"
echo ""
echo "    Backend   http://localhost:8000"
echo "    Frontend  http://localhost:5000"
echo ""
