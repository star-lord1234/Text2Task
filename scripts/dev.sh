#!/bin/sh
# Development: API on :8000 (auto-reload) and Vite on :5173 (proxying /api). Ctrl-C stops both.
cd "$(dirname "$0")/.."
.venv/bin/python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000 &
API=$!
trap 'kill $API 2>/dev/null' EXIT INT TERM
cd frontend && pnpm dev
