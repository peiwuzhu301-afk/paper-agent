#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Paper-Agent requires Python 3.11+")
print("Python", sys.version.split()[0])
PY
"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
[ -f .env ] || cp .env.example .env
if command -v npm >/dev/null 2>&1; then
  (cd frontend && npm install)
else
  echo "npm not found; CLI/API are ready, Vue UI setup skipped."
fi
python -m paper_agent.cli doctor
