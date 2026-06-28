#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT_DIR/apps/api"
WEB_DIR="$ROOT_DIR/apps/web"
LOG_DIR="$ROOT_DIR/logs"

API_PORT="${API_PORT:-8001}"
WEB_PORT="${WEB_PORT:-5173}"

mkdir -p "$LOG_DIR"

is_listening() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

api_dev_command() {
  if [ -f "$API_DIR/.venv/bin/activate" ]; then
    printf 'source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port %s' "$API_PORT"
  elif [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
    printf 'source "%s/.venv/bin/activate" && uvicorn app.main:app --reload --host 0.0.0.0 --port %s' "$ROOT_DIR" "$API_PORT"
  else
    printf 'uvicorn app.main:app --reload --host 0.0.0.0 --port %s' "$API_PORT"
  fi
}

if is_listening "$API_PORT"; then
  echo "API already running on http://localhost:$API_PORT"
else
  echo "Starting API on http://localhost:$API_PORT"
  (
    cd "$API_DIR"
    bash -lc "$(api_dev_command)" 2>&1 | tee -a "$LOG_DIR/api-dev.log"
  ) &
  API_PID=$!
fi

if is_listening "$WEB_PORT"; then
  echo "Web already running on http://localhost:$WEB_PORT"
else
  echo "Starting web on http://localhost:$WEB_PORT"
  (
    cd "$ROOT_DIR"
    npm --prefix "$WEB_DIR" run dev -- --host 0.0.0.0 --port "$WEB_PORT" 2>&1 | tee -a "$LOG_DIR/web-dev.log"
  ) &
  WEB_PID=$!
fi

echo "Logs:"
echo "  API: $LOG_DIR/api-dev.log"
echo "  Web: $LOG_DIR/web-dev.log"

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "Stopping test dev services..."
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

wait
