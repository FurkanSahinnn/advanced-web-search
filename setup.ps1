<#
.SYNOPSIS
  Interactive first-time setup for Advanced Web Search (Windows PowerShell).

.DESCRIPTION
  Detects your environment, lets you CHOOSE how to install (conda / venv /
  system Python), installs the backend, builds the SPA, optionally pre-downloads
  the models, and records the chosen Python interpreter in ".awsearch_env" so
  that .\start.ps1 can launch instantly afterwards.

  Run once:   .\setup.ps1
  Then:       .\start.ps1
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

function Have-Command($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Ask($prompt, $default) {
    if ($default) {
        $a = Read-Host "$prompt [$default]"
        if ([string]::IsNullOrWhiteSpace($a)) { return $default } else { return $a }
    }
    else { return Read-Host $prompt }
}

function Confirm-Yn($prompt) {
    $a = Read-Host "$prompt [y/N]"
    return ($a -match '^(y|yes)$')
}

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  Advanced Web Search - setup" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# --- Detect what's available --------------------------------------------------
$hasConda = Have-Command "conda"
$hasUv = Have-Command "uv"
$hasPnpm = Have-Command "pnpm"
$hasPy = Have-Command "python"
Write-Host ("  - conda:  {0}" -f $(if ($hasConda) { "found" } else { "not found" }))
Write-Host ("  - uv:     {0}" -f $(if ($hasUv) { "found" } else { "not found" }))
Write-Host ("  - python: {0}" -f $(if ($hasPy) { (& python --version) } else { "not found" }))
Write-Host ("  - pnpm:   {0}" -f $(if ($hasPnpm) { "found" } else { "not found (needed to build the UI)" }))
if ($env:CONDA_PREFIX) { Write-Host "  - active conda env: $env:CONDA_PREFIX" }
Write-Host ""

# --- Choose an environment strategy ------------------------------------------
Write-Host "How do you want to install?"
Write-Host "  1) conda         (recommended - isolated, reproducible)"
Write-Host "  2) venv / uv     (lightweight, local .venv)"
Write-Host "  3) system python (advanced - installs into your current python)"
$choice = Ask "Choose 1/2/3" "1"

$py = $null
$envKind = $null
$condaEnvName = $null

function Install-Miniconda {
    $url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
    $exe = Join-Path $env:TEMP "miniconda_setup.exe"
    Write-Host "Downloading Miniconda: $url"
    Invoke-WebRequest -Uri $url -OutFile $exe
    $target = Join-Path $env:USERPROFILE "miniconda3"
    Write-Host "Installing Miniconda silently to $target ..."
    Start-Process -FilePath $exe -ArgumentList "/InstallationType=JustMe", "/AddToPath=0", "/RegisterPython=0", "/S", "/D=$target" -Wait
    Remove-Item $exe -ErrorAction SilentlyContinue
    return $target
}

switch ($choice) {
    "1" {
        $condaExe = $null
        if (-not $hasConda) {
            Write-Host "conda is not installed."
            if (Confirm-Yn "Install Miniconda now into your user profile?") {
                $base = Install-Miniconda
                $condaExe = Join-Path $base "Scripts\conda.exe"
            }
            else {
                Write-Host "Cannot continue with conda. Re-run and pick venv, or install conda yourself."
                exit 1
            }
        }
        else {
            $condaExe = (Get-Command conda).Source
        }
        $condaBase = (& $condaExe info --base).Trim()
        if ($env:CONDA_PREFIX -and (Confirm-Yn "Use the ACTIVE conda env ($env:CONDA_PREFIX)?")) {
            $py = Join-Path $env:CONDA_PREFIX "python.exe"
            $condaEnvName = Split-Path -Leaf $env:CONDA_PREFIX
        }
        else {
            $condaEnvName = Ask "conda env name" "myenv"
            $envDir = Join-Path $condaBase "envs\$condaEnvName"
            if (Test-Path $envDir) {
                Write-Host "Using existing conda env: $condaEnvName"
            }
            else {
                $pyver = Ask "Python version for the new env" "3.12"
                Write-Host "Creating conda env '$condaEnvName' (python=$pyver) ..."
                & $condaExe create -y -n $condaEnvName "python=$pyver"
            }
            $py = Join-Path $envDir "python.exe"
        }
        $envKind = "conda"
    }
    "2" {
        $envKind = "venv"
        $venvPy = ".venv\Scripts\python.exe"
        if ((Test-Path $venvPy) -and (-not (Confirm-Yn "A .venv already exists - recreate it?"))) {
            # keep existing .venv
        }
        else {
            if ($hasUv) { uv venv .venv } else { python -m venv .venv }
        }
        $py = (Resolve-Path $venvPy).Path
    }
    "3" {
        $envKind = "system"
        $py = (Get-Command python).Source
    }
    default { Write-Host "Invalid choice."; exit 1 }
}

Write-Host ""
Write-Host "==> Python: $py" -ForegroundColor Green
& $py --version

# --- Install the backend ------------------------------------------------------
Write-Host "==> Installing backend (pip install -e .)" -ForegroundColor Cyan
& $py -m pip install --upgrade pip 2>$null
& $py -m pip install -e .

# --- Build the SPA ------------------------------------------------------------
if (-not (Test-Path "backend\advanced_web_search\web\index.html")) {
    if ($hasPnpm) {
        Write-Host "==> Building the frontend SPA (pnpm)" -ForegroundColor Cyan
        Push-Location "frontend"
        try {
            if (Have-Command "corepack") { corepack enable }
            pnpm install
            pnpm build
        }
        finally { Pop-Location }
    }
    else {
        Write-Warning "pnpm not found - UI will not be built. Install Node 18+ and pnpm, then: pnpm --dir frontend install; pnpm --dir frontend build"
    }
}
else {
    Write-Host "==> SPA already built" -ForegroundColor DarkGray
}

# --- Optional: pre-download the models ---------------------------------------
if (Confirm-Yn "Pre-download the embedding + reranker models now (~2-3 GB)?") {
    Write-Host "==> Warming up models (this can take a while)..."
    try { & $py -c "from advanced_web_search.embeddings import embedder, reranker; embedder.warm_up(); reranker.warm_up()" }
    catch { Write-Host "Model warm-up failed (non-fatal; they download on first run instead)." }
}

# --- Record the choice for .\start.ps1 ---------------------------------------
$lines = @(
    "# Advanced Web Search environment - written by setup. Machine-specific; do not commit.",
    "AWSEARCH_PY=$py",
    "AWSEARCH_ENV_KIND=$envKind"
)
if ($condaEnvName) { $lines += "AWSEARCH_CONDA_ENV=$condaEnvName" }
$lines | Set-Content -Encoding utf8 ".awsearch_env"

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  Setup complete. Launch any time with:   .\start.ps1" -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan
