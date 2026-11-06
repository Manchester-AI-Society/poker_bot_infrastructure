#!/usr/bin/env bash
# Run the server for an event on any network (eduroam included).
#
#   ./scripts/event.sh up         start server + tunnel, print URL + signup command
#   ./scripts/event.sh url        re-print the public URL (warns if it's dead)
#   ./scripts/event.sh newurl     tunnel died? get a fresh URL (keys + games survive)
#   ./scripts/event.sh key NAME   issue a key on the spot (live + saved to .env)
#   ./scripts/event.sh rehearse   10 bots play a tournament through the tunnel
#   ./scripts/event.sh reset      restart server: wipes tournament + self-registered keys
#   ./scripts/event.sh logs       follow server logs
#   ./scripts/event.sh down       stop everything
set -euo pipefail
cd "$(dirname "$0")/.."

compose() { docker compose --profile tunnel "$@"; }

url() {
  for _ in $(seq 30); do
    found=$(compose logs tunnel 2>/dev/null \
      | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 || true)
    if [ -n "$found" ]; then echo "$found"; return; fi
    sleep 1
  done
  echo "No tunnel URL after 30s — check: docker compose logs tunnel" >&2
  return 1
}

# Is the tunnel serving? Asks 1.1.1.1 directly: querying the system resolver
# before a new hostname exists makes macOS cache "not found" for minutes.
alive() {
  local host=${1#https://} ip
  for _ in $(seq "${2:-20}"); do
    ip=$(dig +short "$host" @1.1.1.1 2>/dev/null | grep -m1 '^[0-9.]*$' || true)
    [ -n "$ip" ] && curl -sf -m 10 --resolve "$host:443:$ip" "$1/health" >/dev/null && return
    sleep 1
  done
  return 1
}

case "${1:-}" in
  up)
    [ -f .env ] || { cp exampleenv .env; echo "Created .env from exampleenv (dev keys — change before a real event)"; }
    # Join code for self-registration (POST /v1/register); generated once, kept in .env.
    if ! grep -q '^REGISTRATION_CODE=.' .env; then
      grep -v '^REGISTRATION_CODE=' .env > .env.tmp || true
      echo "REGISTRATION_CODE=$(openssl rand -hex 3)" >> .env.tmp && mv .env.tmp .env
    fi
    code=$(grep '^REGISTRATION_CODE=' .env | cut -d= -f2-)
    compose up --build -d
    u=$(url)
    alive "$u" 30 && echo "Health: OK" || echo "Health: not reachable yet — try ./scripts/event.sh url in a minute"
    echo
    echo "Server URL:  $u"
    echo
    echo "Put this on the screen — players get their own key with:"
    echo
    echo "  curl -X POST $u/v1/register -H 'Content-Type: application/json' \\"
    echo "    -d '{\"player_id\": \"YOUR-TEAM-NAME\", \"code\": \"$code\"}'"
    ;;
  url)
    u=$(url); echo "$u"
    alive "$u" 1 \
      || echo "Not responding — Cloudflare may have dropped it. Run: ./scripts/event.sh newurl" >&2
    ;;
  newurl)
    # Recreate (not restart) so the old URL isn't left in the logs.
    compose up -d --force-recreate tunnel
    u=$(url)
    alive "$u" 30 && echo "Health: OK" || echo "Health: not reachable yet — try ./scripts/event.sh url in a minute"
    echo "New URL (re-share it): $u"
    ;;
  key)
    name="${2:?usage: ./scripts/event.sh key <team-name>}"
    # Names go into a comma/colon-separated env var, keep them simple.
    [[ "$name" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Name: letters, digits, - and _ only" >&2; exit 1; }
    grep -Eq "^BOT_API_KEYS=(.*,)?$name:" .env && { echo "$name already has a key: grep BOT_API_KEYS .env" >&2; exit 1; }
    k=$(openssl rand -hex 16)
    admin=$(grep '^POKER_ADMIN_API_KEY=' .env | cut -d= -f2-)
    # Live: works immediately, no restart.
    curl -sf -X POST http://127.0.0.1:8000/v1/admin/players \
      -H "Authorization: Bearer $admin" -H "Content-Type: application/json" \
      -d "{\"player_id\": \"$name\", \"api_key\": \"$k\"}" | grep -q '"created":true' \
      || { echo "Server refused: not running, or '$name' already registered itself" >&2; exit 1; }
    # Persist: survives reset/restart.
    if grep -q '^BOT_API_KEYS=.' .env; then
      sed -i.bak "s/^BOT_API_KEYS=.*/&,$name:$k/" .env && rm .env.bak
    else
      grep -v '^BOT_API_KEYS=' .env > .env.tmp || true
      echo "BOT_API_KEYS=$name:$k" >> .env.tmp && mv .env.tmp .env
    fi
    echo "Send to $name:"
    echo "  POKER_SERVER_URL=$(url)"
    echo "  POKER_API_KEY=$k"
    ;;
  rehearse)
    POKER_SERVER_URL=$(url) python examples/bots/remote/simulate_devices.py --bots "${2:-10}"
    ;;
  reset) compose restart poker-server ;;
  logs) compose logs -f poker-server ;;
  down) compose down ;;
  *) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
