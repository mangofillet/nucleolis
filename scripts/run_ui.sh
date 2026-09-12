#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../ui"
npm run dev -- --port "${PORT:-5173}" --host 127.0.0.1
