$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& .\.venv\Scripts\Activate.ps1
paper-agent serve
