#!/usr/bin/env bash
# Read-only API over the current snapshot. No network access required.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=src .venv/Scripts/python.exe -m uvicorn nucleolis.api.main:app --port "${PORT:-8079}"
