#!/usr/bin/env bash
# Start the RAT dashboard
cd "$(dirname "$0")"
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 "$@"
