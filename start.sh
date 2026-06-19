#!/usr/bin/env bash
#
# One-command launcher for Advanced Web Search (macOS / Linux).
#
# Picks a Python environment in this priority order:
#   1. An ACTIVE conda env ($CONDA_PREFIX set) — installs into it, never creates a venv.
#   2. An existing local .venv.
#   3. The current python3 if Advanced Web Search is already installed there.
#   4. Otherwise creates a local .venv as a last resort.
# Installs the backend (editable) if needed, builds the SPA if missing, then
# launches the app at http://127.0.0.1:8787. Extra args pass through to advanced_web_search.
#
#   conda activate myenv && ./start.sh
#   ./start.sh --port 9000 --no-browser
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

have() { command -v "$1" >/dev/null 2>&1; }

echo "== Advanced Web Search launcher =="

# --- 1) Pick the Python interpreter ------------------------------------------
PY=""
if [ -n "${CONDA_PREFIX:-}" ]; then
    PY="$CONDA_PREFIX/bin/python"
    echo "==> Using active conda env: $CONDA_PREFIX"
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
    echo "==> Using existing .venv"
elif have python3 && python3 -c "import advanced_web_search" >/dev/null 2>&1; then
    PY="python3"
    echo "==> Using current python3 (advanced_web_search already installed)"
else
    echo "==> No active environment detected; creating a local .venv."
    echo "    Tip: 'conda activate <env>' before running to install into that env instead."
    if have uv; then uv venv .venv; elif have python3; then python3 -m venv .venv; else python -m venv .venv; fi
    PY=".venv/bin/python"
fi

# --- 2) Install Advanced Web Search into the chosen environment if missing ----------------
if ! "$PY" -c "import advanced_web_search" >/dev/null 2>&1; then
    echo "==> Installing Advanced Web Search (pip install -e .)"
    "$PY" -m pip install -e .
else
    echo "==> Advanced Web Search already installed"
fi

# --- 3) Build the SPA if missing ---------------------------------------------
if [ ! -f "backend/advanced_web_search/web/index.html" ]; then
    if have pnpm; then
        echo "==> Building the frontend SPA (pnpm)"
        ( cd frontend && { have corepack && corepack enable || true; } && pnpm install && pnpm build )
    else
        echo "WARNING: SPA not built and pnpm not found; the UI will be unavailable."
        echo "         Install Node 18+ and pnpm, then: pnpm --dir frontend install && pnpm --dir frontend build"
    fi
else
    echo "==> SPA already built (backend/advanced_web_search/web)"
fi

# --- 4) Launch ----------------------------------------------------------------
echo "==> Starting Advanced Web Search"
exec "$PY" -m advanced_web_search "$@"
