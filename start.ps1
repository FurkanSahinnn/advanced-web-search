<#
.SYNOPSIS
  One-command launcher for Advanced Web Search (Windows PowerShell).

.DESCRIPTION
  Reads the environment chosen by .\setup.ps1 (.awsearch_env) and launches the
  app at http://127.0.0.1:8787. Run .\setup.ps1 once first. Extra args
  (e.g. --port 9000, --no-browser) are passed through to `python -m advanced_web_search`.

.EXAMPLE
  .\start.ps1
  .\start.ps1 --port 9000 --no-browser
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

if (-not (Test-Path ".awsearch_env")) {
    Write-Error "No environment configured yet. Run .\setup.ps1 first."
    exit 1
}

# Read the recorded interpreter (value may contain spaces -> keep everything after '=').
$pyLine = Get-Content ".awsearch_env" | Where-Object { $_ -match '^AWSEARCH_PY=' } | Select-Object -First 1
$py = if ($pyLine) { $pyLine -replace '^AWSEARCH_PY=', '' } else { $null }
if ((-not $py) -or (-not (Test-Path $py))) {
    Write-Error "Configured Python not found: '$py'. Re-run .\setup.ps1."
    exit 1
}

& $py -c "import advanced_web_search" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "advanced_web_search is not installed in the configured env. Re-run .\setup.ps1."
    exit 1
}

if (-not (Test-Path "backend\advanced_web_search\web\index.html")) {
    Write-Warning "SPA not built - the UI will be unavailable (the API still runs). Re-run .\setup.ps1."
}

Write-Host "==> Starting Advanced Web Search" -ForegroundColor Green
& $py -m advanced_web_search @args
