<#
.SYNOPSIS
  One-command launcher for Advanced Web Search (Windows PowerShell).

.DESCRIPTION
  Picks a Python environment in this priority order:
    1. An ACTIVE conda env (if $env:CONDA_PREFIX is set) — installs into it, never creates a venv.
    2. An existing local .venv.
    3. The current `python` if Advanced Web Search is already installed there.
    4. Otherwise creates a local .venv as a last resort.
  Installs the backend (editable) if needed, builds the SPA if it has not been
  built, then launches the app at http://127.0.0.1:8787. Extra args
  (e.g. --port 9000, --no-browser) are passed through to `python -m advanced_web_search`.

.EXAMPLE
  conda activate myenv ; ./start.ps1
  ./start.ps1 --port 9000 --no-browser
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

function Have-Command($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

Write-Host "== Advanced Web Search launcher ==" -ForegroundColor Cyan

# --- 1) Pick the Python interpreter ------------------------------------------
$py = $null
if ($env:CONDA_PREFIX) {
    $py = Join-Path $env:CONDA_PREFIX "python.exe"
    Write-Host "==> Using active conda env: $env:CONDA_PREFIX" -ForegroundColor Green
}
elseif (Test-Path ".venv\Scripts\python.exe") {
    $py = (Resolve-Path ".venv\Scripts\python.exe").Path
    Write-Host "==> Using existing .venv" -ForegroundColor DarkGray
}
else {
    $hasPkg = $false
    if (Have-Command "python") { & python -c "import advanced_web_search" 2>$null; $hasPkg = ($LASTEXITCODE -eq 0) }
    if ($hasPkg) {
        $py = "python"
        Write-Host "==> Using current Python (advanced_web_search already installed)" -ForegroundColor DarkGray
    }
    else {
        Write-Host "==> No active environment detected; creating a local .venv." -ForegroundColor Yellow
        Write-Host "    Tip: 'conda activate <env>' before running to install into that env instead."
        if (Have-Command "uv") { uv venv .venv } else { python -m venv .venv }
        $py = (Resolve-Path ".venv\Scripts\python.exe").Path
    }
}

# --- 2) Install Advanced Web Search into the chosen environment if missing ----------------
& $py -c "import advanced_web_search" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> Installing Advanced Web Search (pip install -e .)" -ForegroundColor Cyan
    & $py -m pip install -e .
}
else {
    Write-Host "==> Advanced Web Search already installed" -ForegroundColor DarkGray
}

# --- 3) Build the SPA if missing ---------------------------------------------
if (-not (Test-Path "backend\advanced_web_search\web\index.html")) {
    if (Have-Command "pnpm") {
        Write-Host "==> Building the frontend SPA (pnpm)" -ForegroundColor Cyan
        Push-Location "frontend"
        try {
            if (Have-Command "corepack") { corepack enable }
            pnpm install
            pnpm build
        } finally { Pop-Location }
    }
    else {
        Write-Warning "SPA not built and pnpm not found; the API will run but the UI will be unavailable."
        Write-Host "    Install Node 18+ and pnpm, then: pnpm --dir frontend install; pnpm --dir frontend build"
    }
}
else {
    Write-Host "==> SPA already built (backend/advanced_web_search/web)" -ForegroundColor DarkGray
}

# --- 4) Launch ----------------------------------------------------------------
Write-Host "==> Starting Advanced Web Search" -ForegroundColor Green
& $py -m advanced_web_search @args
