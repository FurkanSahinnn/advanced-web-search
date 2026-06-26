#!/usr/bin/env bash
#
# Interactive first-time setup for Advanced Web Search (macOS / Linux).
#
# Detects your environment, lets you CHOOSE how to install (conda / venv / uv /
# system Python), installs the backend, builds the SPA, optionally pre-downloads
# the models, and records the chosen Python interpreter in ".awsearch_env" so
# that ./start.sh can launch instantly afterwards.
#
#   Run once:   ./setup.sh
#   Then:       ./start.sh
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

have() { command -v "$1" >/dev/null 2>&1; }

# ask "prompt" "default" -> echoes the answer (default on empty input)
ask() {
    local prompt="$1" def="${2:-}" ans
    if [ -n "$def" ]; then
        read -r -p "$prompt [$def]: " ans || true
        echo "${ans:-$def}"
    else
        read -r -p "$prompt: " ans || true
        echo "$ans"
    fi
}

# confirm "prompt" -> returns 0 on yes, 1 otherwise (default No)
confirm() {
    local ans
    read -r -p "$1 [y/N]: " ans || true
    case "$ans" in [yY] | [yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

echo "=================================================================="
echo "  Advanced Web Search — setup"
echo "=================================================================="

# --- Detect what's available --------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"
echo "System: $OS / $ARCH"
if have conda; then echo "  - conda:   found ($(command -v conda))"; else echo "  - conda:   not found"; fi
if have uv; then echo "  - uv:      found"; else echo "  - uv:      not found"; fi
if have python3; then echo "  - python3: $(python3 --version 2>&1)"; else echo "  - python3: not found"; fi
if have pnpm; then echo "  - pnpm:    found"; else echo "  - pnpm:    not found (needed to build the UI)"; fi
[ -n "${CONDA_PREFIX:-}" ] && echo "  - active conda env: $CONDA_PREFIX"
echo

# --- Choose an environment strategy ------------------------------------------
echo "How do you want to install?"
echo "  1) conda          (recommended — isolated, reproducible)"
echo "  2) venv / uv      (lightweight, local .venv)"
echo "  3) system python3 (advanced — installs into your current python3)"
CHOICE="$(ask "Choose 1/2/3" "1")"

PY=""
ENV_KIND=""
CONDA_ENV_NAME=""

install_miniconda() {
    local mc_os mc_arch url tmp
    case "$OS" in
        Linux) mc_os="Linux" ;;
        Darwin) mc_os="MacOSX" ;;
        *) echo "Unsupported OS for auto-install: $OS"; return 1 ;;
    esac
    case "$ARCH" in
        x86_64 | amd64) mc_arch="x86_64" ;;
        aarch64) mc_arch="aarch64" ;;
        arm64) [ "$mc_os" = "MacOSX" ] && mc_arch="arm64" || mc_arch="aarch64" ;;
        *) echo "Unsupported arch for auto-install: $ARCH"; return 1 ;;
    esac
    url="https://repo.anaconda.com/miniconda/Miniconda3-latest-${mc_os}-${mc_arch}.sh"
    tmp="$(mktemp -t miniconda-XXXXXX.sh)"
    echo "Downloading Miniconda: $url"
    if have curl; then curl -fsSL "$url" -o "$tmp"
    elif have wget; then wget -qO "$tmp" "$url"
    else echo "Need curl or wget to download Miniconda."; return 1; fi
    bash "$tmp" -b -p "$HOME/miniconda3"
    rm -f "$tmp"
    export PATH="$HOME/miniconda3/bin:$PATH"
    echo "Miniconda installed at $HOME/miniconda3"
}

case "$CHOICE" in
    1)
        if ! have conda; then
            echo "conda is not installed."
            if confirm "Install Miniconda now into ~/miniconda3?"; then
                install_miniconda || { echo "Miniconda install failed."; exit 1; }
            else
                echo "Cannot continue with conda. Re-run and pick venv, or install conda yourself."
                exit 1
            fi
        fi
        CONDA_BASE="$(conda info --base)"
        if [ -n "${CONDA_PREFIX:-}" ] && confirm "Use the ACTIVE conda env ($CONDA_PREFIX)?"; then
            PY="$CONDA_PREFIX/bin/python"
            CONDA_ENV_NAME="$(basename "$CONDA_PREFIX")"
        else
            CONDA_ENV_NAME="$(ask "conda env name" "myenv")"
            if [ -d "$CONDA_BASE/envs/$CONDA_ENV_NAME" ]; then
                echo "Using existing conda env: $CONDA_ENV_NAME"
            else
                PYVER="$(ask "Python version for the new env" "3.12")"
                echo "Creating conda env '$CONDA_ENV_NAME' (python=$PYVER)..."
                conda create -y -n "$CONDA_ENV_NAME" "python=$PYVER"
            fi
            PY="$CONDA_BASE/envs/$CONDA_ENV_NAME/bin/python"
        fi
        ENV_KIND="conda"
        ;;
    2)
        ENV_KIND="venv"
        if [ -x ".venv/bin/python" ] && ! confirm "A .venv already exists — recreate it?"; then
            : # keep existing .venv
        else
            if have uv; then uv venv .venv
            elif have python3; then python3 -m venv .venv
            else python -m venv .venv; fi
        fi
        PY=".venv/bin/python"
        ;;
    3)
        ENV_KIND="system"
        if have python3; then PY="$(command -v python3)"; else PY="$(command -v python)"; fi
        ;;
    *)
        echo "Invalid choice."; exit 1 ;;
esac

# Resolve to an absolute path where possible (start.sh stores/uses this verbatim).
if have realpath; then PY="$(realpath "$PY" 2>/dev/null || echo "$PY")"; fi

echo
echo "==> Python: $PY"
"$PY" --version || { echo "Selected Python is not runnable."; exit 1; }

# --- Install the backend ------------------------------------------------------
echo "==> Installing backend (pip install -e .)"
"$PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
"$PY" -m pip install -e .

# --- Build the SPA ------------------------------------------------------------
if [ ! -f "backend/advanced_web_search/web/index.html" ]; then
    if have pnpm; then
        echo "==> Building the frontend SPA (pnpm)"
        (cd frontend && { have corepack && corepack enable || true; } && pnpm install && pnpm build)
    else
        echo "WARNING: pnpm not found — UI will not be built. Install Node 18+ and pnpm, then:"
        echo "         pnpm --dir frontend install && pnpm --dir frontend build"
    fi
else
    echo "==> SPA already built"
fi

# --- Optional: pre-download the models ---------------------------------------
if confirm "Pre-download the embedding + reranker models now (~2-3 GB)?"; then
    echo "==> Warming up models (this can take a while)..."
    "$PY" -c "from advanced_web_search.embeddings import embedder, reranker; embedder.warm_up(); reranker.warm_up()" ||
        echo "Model warm-up failed (non-fatal; they download on first run instead)."
fi

# --- Record the choice for ./start.sh ----------------------------------------
{
    echo "# Advanced Web Search environment — written by setup. Machine-specific; do not commit."
    echo "AWSEARCH_PY=$PY"
    echo "AWSEARCH_ENV_KIND=$ENV_KIND"
    [ -n "$CONDA_ENV_NAME" ] && echo "AWSEARCH_CONDA_ENV=$CONDA_ENV_NAME"
} >.awsearch_env

echo
echo "=================================================================="
echo "  Setup complete. Launch any time with:   ./start.sh"
echo "=================================================================="
