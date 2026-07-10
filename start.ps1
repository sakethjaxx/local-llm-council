# LLM Council — one-command setup + start (Windows)
$ErrorActionPreference = "Stop"

Write-Host "Starting Local LLM Council..." -ForegroundColor Green

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python 3.12+ is required but was not found." -ForegroundColor Red
    Write-Host "Install it from https://www.python.org/downloads/ and re-run this script."
    exit 1
}

$pyVersion = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pyVersion -lt [version]"3.12") {
    Write-Host "Python $pyVersion found, but 3.12+ is required." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
}

Write-Host "Installing dependencies (first run can take a few minutes)..." -ForegroundColor Yellow
& ".\venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
$env:PYTHONPATH = (Join-Path (Get-Location) "src")

if (-not (Test-Path ".env") -and (Test-Path "env.example")) {
    Copy-Item "env.example" ".env"
    Write-Host "Created .env from env.example (defaults are fine for local use)." -ForegroundColor Yellow
}

try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 | Out-Null
    Write-Host "Ollama detected." -ForegroundColor Green
} catch {
    Write-Host "Warning: Ollama is not reachable at http://localhost:11434." -ForegroundColor Yellow
    Write-Host "The UI will start, but council runs need Ollama:"
    Write-Host "  1. Install: https://ollama.com/download"
    Write-Host "  2. Start it, then: ollama pull llama3.2"
}

Write-Host "Server starting on http://localhost:8765" -ForegroundColor Cyan
& ".\venv\Scripts\python.exe" -m llm_council.main
