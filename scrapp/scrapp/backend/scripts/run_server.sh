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
PORT="${PORT:-8000}"
# Phone over USB: keep `adb reverse` alive. The tunnel silently disappears (cable blip, adb restart, another
# tool resetting adb) and the app's images then fail with ERR_CONNECTION_REFUSED while the server looks fine.
if command -v adb >/dev/null 2>&1; then
  ( while true; do
      if adb get-state >/dev/null 2>&1 && ! adb reverse --list 2>/dev/null | grep -q "tcp:$PORT"; then
        adb reverse "tcp:$PORT" "tcp:$PORT" >/dev/null 2>&1 && echo "[run_server] restored adb reverse tcp:$PORT"
      fi
      sleep 5
    done ) &
  trap 'kill $! 2>/dev/null' EXIT
fi
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
