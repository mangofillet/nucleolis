#!/usr/bin/env bash
# Full rebuild: CoGEx -> raw -> normalized -> validated snapshot.
# Needs network. Takes ~10 minutes (1362 throttled evidence calls).
set -euo pipefail
cd "$(dirname "$0")/.."
LABEL="${1:-demo_$(date +%Y%m%dT%H%M%SZ)}"
PY="PYTHONPATH=src .venv/Scripts/python.exe"
eval $PY -m nucleolus.pipeline.retrieve --max-nodes "${MAX_NODES:-60}" --evidence-for all
eval $PY -m nucleolus.pipeline.normalize
eval $PY -m nucleolus.pipeline.build --label "$LABEL"
echo "snapshot ready: $LABEL  (restart the API to serve it)"
