#!/usr/bin/env bash
# Full rebuild: CoGEx -> raw -> normalized -> enriched -> validated snapshot.
# Needs network.
#
#   scripts/rebuild_snapshot.sh [label]
#
# EVIDENCE_CAP=N   keep at most N evidence records per claim in the snapshot.
#                  Unset = full sentence trail (large: the brain-ageing snapshot
#                  is ~900MB and the API holds it in memory). Paper counts are
#                  exact either way; only stored sentences are sampled.
#   MAX_NODES=N    node universe ceiling (default 500).
set -euo pipefail
cd "$(dirname "$0")/.."

# Windows checkout puts the interpreter under Scripts/; POSIX under bin/.
PY=".venv/Scripts/python.exe"
[ -x "$PY" ] || PY=".venv/bin/python"
[ -x "$PY" ] || { echo "no virtualenv interpreter found - run: uv venv" >&2; exit 1; }

LABEL="${1:-demo_$(date +%Y%m%dT%H%M%SZ)}"
CAP_ARG=()
[ -n "${EVIDENCE_CAP:-}" ] && CAP_ARG=(--max-evidence-per-claim "$EVIDENCE_CAP")

export PYTHONPATH=src
"$PY" -m nucleolis.pipeline.retrieve --max-nodes "${MAX_NODES:-500}" --evidence-for all
"$PY" -m nucleolis.pipeline.normalize
"$PY" -m nucleolis.pipeline.enrich
"$PY" -m nucleolis.pipeline.build --label "$LABEL" "${CAP_ARG[@]}"
echo "snapshot ready: $LABEL  (restart the API to serve it)"
