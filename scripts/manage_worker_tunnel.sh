#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 <start|stop|restart|status|_loop> <config.env>" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage
ACTION="$1"
CONFIG_FILE="$2"
[[ -r "$CONFIG_FILE" ]] || { echo "config is not readable: $CONFIG_FILE" >&2; exit 2; }
CONFIG_FILE="$(cd "$(dirname "$CONFIG_FILE")" && pwd)/$(basename "$CONFIG_FILE")"

# The config is an operator-owned shell env file and must be mode 600 or stricter.
CONFIG_MODE="$(stat -f '%Lp' "$CONFIG_FILE" 2>/dev/null || stat -c '%a' "$CONFIG_FILE")"
if (( 10#$CONFIG_MODE % 100 != 0 )); then
  echo "config must not be group/world accessible: $CONFIG_FILE (mode $CONFIG_MODE)" >&2
  exit 2
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"
: "${TUNNEL_NAME:?set TUNNEL_NAME}"
: "${TUNNEL_SSH_TARGET:?set TUNNEL_SSH_TARGET}"
: "${TUNNEL_SSH_KEY:?set TUNNEL_SSH_KEY}"
TUNNEL_REMOTE_BIND="${TUNNEL_REMOTE_BIND:-127.0.0.1}"
TUNNEL_REMOTE_PORT="${TUNNEL_REMOTE_PORT:-18765}"
TUNNEL_LOCAL_HOST="${TUNNEL_LOCAL_HOST:-127.0.0.1}"
TUNNEL_LOCAL_PORT="${TUNNEL_LOCAL_PORT:-8765}"
TUNNEL_RETRY_SECONDS="${TUNNEL_RETRY_SECONDS:-5}"
TUNNEL_STATE_DIR="${TUNNEL_STATE_DIR:-.runtime/worker-tunnels}"

[[ -r "$TUNNEL_SSH_KEY" ]] || { echo "SSH key is not readable: $TUNNEL_SSH_KEY" >&2; exit 2; }
mkdir -p "$TUNNEL_STATE_DIR"
TUNNEL_STATE_DIR="$(cd "$TUNNEL_STATE_DIR" && pwd)"
PID_FILE="$TUNNEL_STATE_DIR/$TUNNEL_NAME.pid"
LOG_FILE="$TUNNEL_STATE_DIR/$TUNNEL_NAME.log"

is_running() {
  [[ -s "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

run_loop() {
  trap 'exit 0' TERM INT
  while true; do
    ssh \
      -i "$TUNNEL_SSH_KEY" \
      -o BatchMode=yes \
      -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=15 \
      -o ServerAliveCountMax=3 \
      -o StrictHostKeyChecking=accept-new \
      -NT \
      -R "$TUNNEL_REMOTE_BIND:$TUNNEL_REMOTE_PORT:$TUNNEL_LOCAL_HOST:$TUNNEL_LOCAL_PORT" \
      "$TUNNEL_SSH_TARGET" || true
    sleep "$TUNNEL_RETRY_SECONDS"
  done
}

start_tunnel() {
  if is_running; then
    echo "$TUNNEL_NAME already running (pid $(cat "$PID_FILE"))"
    return
  fi
  rm -f "$PID_FILE"
  nohup "$0" _loop "$CONFIG_FILE" >>"$LOG_FILE" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" >"$PID_FILE"
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    tail -n 80 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    exit 3
  fi
  echo "$TUNNEL_NAME started (pid $pid)"
}

stop_tunnel() {
  if ! is_running; then
    rm -f "$PID_FILE"
    echo "$TUNNEL_NAME is stopped"
    return
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill "$pid"
  for _ in {1..20}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.1
  done
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "$TUNNEL_NAME stopped"
}

status_tunnel() {
  if ! is_running; then
    echo "$TUNNEL_NAME stopped"
    return 1
  fi
  local remote_listener_check
  remote_listener_check="ss -lnt | awk '\$4 == "
  remote_listener_check+="\"$TUNNEL_REMOTE_BIND:$TUNNEL_REMOTE_PORT\" "
  remote_listener_check+="{found=1} END {exit !found}'"
  if ssh \
    -i "$TUNNEL_SSH_KEY" \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    "$TUNNEL_SSH_TARGET" \
    "$remote_listener_check"; then
    echo "$TUNNEL_NAME healthy (pid $(cat "$PID_FILE"), remote " \
      "$TUNNEL_REMOTE_BIND:$TUNNEL_REMOTE_PORT)"
    return
  fi
  echo "$TUNNEL_NAME process is running but remote forwarding is not ready" >&2
  return 1
}

case "$ACTION" in
  start) start_tunnel ;;
  stop) stop_tunnel ;;
  restart) stop_tunnel; start_tunnel ;;
  status) status_tunnel ;;
  _loop) run_loop ;;
  *) usage ;;
esac
