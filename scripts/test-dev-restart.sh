#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-8001}"
WEB_PORT="${WEB_PORT:-5173}"

stop_port() {
  local name="$1"
  local port="$2"
  local pids

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN || true)"
  if [ -z "$pids" ]; then
    echo "$name not running on port $port"
    return
  fi

  echo "Stopping $name on port $port: $pids"
  kill $pids || true
  for _ in {1..20}; do
    if ! lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      return
    fi
    sleep 0.25
  done
  echo "$name is still releasing port $port; forcing stop"
  kill -9 $pids 2>/dev/null || true
}

stop_port "API" "$API_PORT"
stop_port "Web" "$WEB_PORT"

sleep 1

exec "$ROOT_DIR/scripts/test-dev-start.sh"
