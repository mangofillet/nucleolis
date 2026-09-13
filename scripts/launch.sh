#!/usr/bin/env bash
# nucleolis - single-command launch.
# Serves the API and the built UI from one process on one port.
# Requires a snapshot in data/snapshots/ (see scripts/rebuild_snapshot.sh).
# Makes no network request.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8077}"
PY=".venv/Scripts/python.exe"
[ -x "$PY" ] || PY=".venv/bin/python"

if [ ! -f data/snapshots/CURRENT ]; then
  echo "No snapshot found. Run: scripts/rebuild_snapshot.sh" >&2
  exit 1
fi

if [ ! -d ui/dist ]; then
  echo "Building UI (first run only)..."
  (cd ui && npm install --silent && npm run build)
fi

echo "nucleolis -> http://127.0.0.1:${PORT}   (snapshot: $(cat data/snapshots/CURRENT))"
PYTHONPATH=src exec "$PY" -m uvicorn nucleolis.api.main:app --host 127.0.0.1 --port "$PORT"
