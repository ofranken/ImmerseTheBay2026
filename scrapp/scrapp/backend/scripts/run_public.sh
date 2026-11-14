#!/usr/bin/env bash
# Run the Scrapp API on this machine and reach it from anywhere through Cloudflare. No USB, no shared Wi-Fi.
#
#   bash scripts/run_public.sh
#
# Three modes (first match wins):
#   Local named tunnel: CLOUDFLARED_CONFIG=~/.cloudflared/scrapp.yml + PUBLIC_HOSTNAME=scrapp.nmagic.dev in .env.
#       A permanent hostname served by a tunnel whose credentials are on this machine.
#   Quick tunnel (default): no account needed. cloudflared prints a random https://<words>.trycloudflare.com
#       URL that changes every run. The server learns it automatically (signed image links need it).
#       Put that URL in the app: Settings -> API base URL.
#   Named tunnel (permanent hostname): set in backend/.env
#       CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Zero Trust -> Networks -> Tunnels>
#       PUBLIC_HOSTNAME=scrapp.nmagic.dev
#       The tunnel's public hostname must route to http://localhost:8000 in the Cloudflare dashboard.
#
# The tunnel is outbound-only: nothing is opened on your router. MongoDB is never exposed, only the API.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
PORT="${PORT:-8000}"

command -v cloudflared >/dev/null || { echo "cloudflared not found. See docs/SETUP.md (Public access)."; exit 1; }
# Read just the keys this script needs. .env is NOT sourced: an Atlas URI contains & and ? that break the shell.
envval() { [ -f .env ] && grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true; }
MONGO_URI="${MONGO_URI:-$(envval MONGO_URI)}"
CLOUDFLARE_TUNNEL_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-$(envval CLOUDFLARE_TUNNEL_TOKEN)}"
PUBLIC_HOSTNAME="${PUBLIC_HOSTNAME:-$(envval PUBLIC_HOSTNAME)}"
CLOUDFLARED_CONFIG="${CLOUDFLARED_CONFIG:-$(envval CLOUDFLARED_CONFIG)}"
CLOUDFLARED_CONFIG="${CLOUDFLARED_CONFIG/#\~/$HOME}"

# Mullvad (and some other VPNs) block Cloudflare's tunnel port (7844). If Mullvad is connected, run ONLY
# cloudflared outside the VPN with Mullvad's per-process bypass; everything else stays tunnelled.
CF=(cloudflared)
if command -v mullvad-exclude >/dev/null 2>&1 && mullvad status 2>/dev/null | grep -q '^Connected'; then
  CF=(mullvad-exclude "$(command -v cloudflared)")
  echo "==> Mullvad is connected: running cloudflared outside the VPN (its tunnel port is blocked inside it)"
fi

TUNNEL_LOG="$(mktemp /tmp/scrapp-tunnel.XXXXXX.log)"
cleanup() { kill "${TUNNEL_PID:-}" 2>/dev/null || true; rm -f .public_url; }
trap cleanup EXIT

# Local dev MongoDB (Docker) only when .env points at localhost; a shared/Atlas URI is left alone.
if [ -z "${MONGO_URI:-}" ] || [[ "${MONGO_URI}" == mongodb://localhost* ]]; then
  docker start scrapp-mongo >/dev/null 2>&1 || docker run -d --name scrapp-mongo --restart unless-stopped \
    -p 127.0.0.1:27017:27017 -v scrapp-mongo-data:/data/db mongo:7 >/dev/null
fi

if [ -n "${CLOUDFLARED_CONFIG:-}" ]; then
  : "${PUBLIC_HOSTNAME:?set PUBLIC_HOSTNAME (e.g. scrapp.nmagic.dev) alongside CLOUDFLARED_CONFIG}"
  [ -f "$CLOUDFLARED_CONFIG" ] || { echo "CLOUDFLARED_CONFIG not found: $CLOUDFLARED_CONFIG"; exit 1; }
  "${CF[@]}" tunnel --no-autoupdate --config "$CLOUDFLARED_CONFIG" run >"$TUNNEL_LOG" 2>&1 &
  TUNNEL_PID=$!
  PUBLIC_URL="https://$PUBLIC_HOSTNAME"
elif [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
  : "${PUBLIC_HOSTNAME:?set PUBLIC_HOSTNAME (e.g. scrapp.nmagic.dev) alongside CLOUDFLARE_TUNNEL_TOKEN}"
  "${CF[@]}" tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN" >"$TUNNEL_LOG" 2>&1 &
  TUNNEL_PID=$!
  PUBLIC_URL="https://$PUBLIC_HOSTNAME"
else
  "${CF[@]}" tunnel --no-autoupdate --url "http://localhost:$PORT" >"$TUNNEL_LOG" 2>&1 &
  TUNNEL_PID=$!
  PUBLIC_URL=""
  for _ in $(seq 1 40); do
    PUBLIC_URL="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" | head -1 || true)"
    [ -n "$PUBLIC_URL" ] && break
    kill -0 "$TUNNEL_PID" 2>/dev/null || { echo "cloudflared exited:"; tail -5 "$TUNNEL_LOG"; exit 1; }
    sleep 1
  done
  [ -n "$PUBLIC_URL" ] || { echo "No tunnel URL after 40s:"; tail -5 "$TUNNEL_LOG"; exit 1; }
fi

export PUBLIC_BASE_URL="$PUBLIC_URL"
echo "$PUBLIC_URL" > .public_url
echo "==> Scrapp API public URL: $PUBLIC_URL"
echo "==> In the app: Settings -> API base URL -> $PUBLIC_URL"

.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
