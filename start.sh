#!/usr/bin/env bash
#
# One-command launcher for Advanced Web Search (macOS / Linux).
#
# Reads the environment chosen by ./setup.sh (.awsearch_env) and launches the
# app at http://127.0.0.1:8787. Run ./setup.sh once first. Extra args
# (e.g. --port 9000, --no-browser) pass through to advanced_web_search.
#
#   ./start.sh
#   ./start.sh --port 9000 --no-browser
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f ".awsearch_env" ]; then
    echo "No environment configured yet. Run ./setup.sh first." >&2
    exit 1
fi

# Read the recorded interpreter (value may contain spaces -> keep everything after '=').
PY="$(grep -E '^AWSEARCH_PY=' .awsearch_env | head -1 | cut -d'=' -f2-)"
if [ -z "${PY:-}" ] || [ ! -x "$PY" ]; then
    echo "Configured Python not found: '${PY:-<empty>}'. Re-run ./setup.sh." >&2
    exit 1
fi

if ! "$PY" -c "import advanced_web_search" >/dev/null 2>&1; then
    echo "advanced_web_search is not installed in the configured env. Re-run ./setup.sh." >&2
    exit 1
fi

if [ ! -f "backend/advanced_web_search/web/index.html" ]; then
    echo "WARNING: SPA not built — the UI will be unavailable (the API still runs)." >&2
    echo "         Re-run ./setup.sh, or: pnpm --dir frontend install && pnpm --dir frontend build" >&2
fi

echo "==> Starting Advanced Web Search"
exec "$PY" -m advanced_web_search "$@"
