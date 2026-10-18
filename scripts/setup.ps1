$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -c "import sys; assert sys.version_info >= (3,11), 'Paper-Agent requires Python 3.11+'; print('Python', sys.version.split()[0])"
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (Get-Command npm -ErrorAction SilentlyContinue) {
  Push-Location frontend
  npm install
  Pop-Location
} else {
  Write-Host "npm not found; CLI/API are ready, Vue UI setup skipped."
}
python -m paper_agent.cli doctor
