#!/bin/sh
# Single-command demo: builds the frontend if needed, then serves API + UI on http://127.0.0.1:8000
# Usage: scripts/run_app.sh            (loads the real models; takes a few seconds)
#        T2T_NO_MODELS=1 scripts/run_app.sh   (scripted demo only, Live mode reports "model unavailable")
set -e
cd "$(dirname "$0")/.."
if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && pnpm install --frozen-lockfile && pnpm build)
fi
exec .venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port "${PORT:-8000}"
