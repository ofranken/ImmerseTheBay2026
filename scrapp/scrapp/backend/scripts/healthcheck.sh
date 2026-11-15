#!/usr/bin/env bash
# Health check for the three Scrapp services. Run every minute by scrapp-health.timer.
#   API     http://127.0.0.1:8000/health            -> restart scrapp-api
#   Studio  http://127.0.0.1:3000/ (200 or 401)     -> restart scrapp-studio
#   Tunnel  https://scrapp.nmagic.dev/health        -> restart scrapp-tunnel
# A service is restarted after 2 failed checks in a row (one blip never restarts anything). The public check is
# skipped when the API itself is down (that would just blame the tunnel) and when the laptop has no internet.
# systemd's Restart=always already handles crashes; this catches hangs (process alive, not answering).
set -u
STATE="${XDG_RUNTIME_DIR:-/tmp}/scrapp-health"
mkdir -p "$STATE"
PUBLIC_URL="${PUBLIC_URL:-https://scrapp.nmagic.dev}"
log() { echo "$(date '+%F %T') $*"; }

code() { curl -s -o /dev/null -m "${2:-8}" -w '%{http_code}' "$1" 2>/dev/null || true; }

check() { # name unit ok_regex url [timeout]
  local name="$1" unit="$2" ok="$3" url="$4" c f="$STATE/$1.fails"
  c="$(code "$url" "${5:-8}")"
  if [[ "$c" =~ $ok ]]; then
    [ -f "$f" ] && log "$name recovered (HTTP $c)"
    rm -f "$f"; return 0
  fi
  local n=$(( $(cat "$f" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$f"
  log "$name check failed ($n/2): HTTP $c"
  if [ "$n" -ge 2 ]; then
    log "restarting $unit"
    systemctl --user restart "$unit"
    rm -f "$f"
  fi
  return 1
}

api_ok=0; check api scrapp-api '^200$' http://127.0.0.1:8000/health 10 && api_ok=1
check studio scrapp-studio '^(200|401)$' http://127.0.0.1:3000/ || true

if [ "$api_ok" = 1 ]; then
  if [ "$(code https://www.cloudflare.com/cdn-cgi/trace 6)" != "200" ]; then
    log "no internet: skipping tunnel check"
  else
    if command -v mullvad >/dev/null 2>&1 && mullvad status 2>/dev/null | grep -q '^Connected'; then
      log "WARNING: Mullvad VPN is connected; it blocks the Cloudflare tunnel port. Disconnect it."
    fi
    check tunnel scrapp-tunnel '^200$' "$PUBLIC_URL/health" 12 || true
  fi
fi
