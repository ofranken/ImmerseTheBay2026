#!/usr/bin/env bash
# Starts the Scrapp API on this laptop: local dev MongoDB (Docker) + uvicorn with the SAM 3 segmenter.
#   bash scripts/run_server.sh              # SEGMENTER from .env
#   SEGMENTER=grabcut bash scripts/run_server.sh   # CPU stand-in, no weights needed
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -n "${MONGO_URI:-}" ] || ! grep -q '^MONGO_URI=mongodb://localhost' .env 2>/dev/null; then
  :  # using a shared/remote Mongo: don't start a local one
else
  docker start scrapp-mongo >/dev/null 2>&1 || docker run -d --name scrapp-mongo --restart unless-stopped \
    -p 127.0.0.1:27017:27017 -v scrapp-mongo-data:/data/db mongo:7 >/dev/null
fi
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
