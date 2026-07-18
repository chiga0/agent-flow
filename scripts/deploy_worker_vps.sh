#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <ssh-target> <ssh-key>" >&2
  exit 2
fi

SSH_TARGET="$1"
SSH_KEY="$2"
APP_DIR="${APP_DIR:-/opt/agentflow}"
STATE_DIR="${STATE_DIR:-/var/lib/cloud-agents-worker}"
REPO_URL="${REPO_URL:-https://github.com/chiga0/agent-flow.git}"
REPO_REF="${REPO_REF:-main}"
REPO_UPDATE="${REPO_UPDATE:-1}"
NODE_PACKAGE="${NODE_PACKAGE:-@qwen-code/qwen-code@0.19.11}"
NODE_VERSION="${NODE_VERSION:-22.22.1}"
QWEN_SETTINGS_FILE="${QWEN_SETTINGS_FILE:-}"
RUN_WORKER_CONTROL_URL="${RUN_WORKER_CONTROL_URL:-}"
RUN_WORKER_TOKEN="${RUN_WORKER_TOKEN:-}"
RUN_WORKER_ID="${RUN_WORKER_ID:-}"
RUN_WORKER_CAPACITY="${RUN_WORKER_CAPACITY:-1}"
RUN_WORKER_LEASE_TTL_SECONDS="${RUN_WORKER_LEASE_TTL_SECONDS:-60}"
RUN_WORKER_POLL_INTERVAL_SECONDS="${RUN_WORKER_POLL_INTERVAL_SECONDS:-2}"
RUN_WORKER_HEARTBEAT_INTERVAL_SECONDS="${RUN_WORKER_HEARTBEAT_INTERVAL_SECONDS:-10}"
RUN_WORKER_RUN_WAIT_TIMEOUT_SECONDS="${RUN_WORKER_RUN_WAIT_TIMEOUT_SECONDS:-300}"
RUN_WORKER_METADATA_JSON="${RUN_WORKER_METADATA_JSON:-}"
if [[ -z "$RUN_WORKER_METADATA_JSON" ]]; then
  RUN_WORKER_METADATA_JSON='{}'
fi
QWEN_SERVE_URL="${QWEN_SERVE_URL:-}"
QWEN_SERVE_TOKEN="${QWEN_SERVE_TOKEN:-}"
QWEN_SERVE_ENV_FILE="${QWEN_SERVE_ENV_FILE:-}"
QWEN_MANAGED_SERVE="${QWEN_MANAGED_SERVE:-auto}"
QWEN_SERVE_HOST="${QWEN_SERVE_HOST:-127.0.0.1}"
QWEN_SERVE_PORT="${QWEN_SERVE_PORT:-4210}"
QWEN_SERVE_WORKSPACE="${QWEN_SERVE_WORKSPACE:-$STATE_DIR/workspace}"
QWEN_SERVE_STARTUP_TIMEOUT_SECONDS="${QWEN_SERVE_STARTUP_TIMEOUT_SECONDS:-60}"
DEPLOY_SSH_CONNECT_TIMEOUT_SECONDS="${DEPLOY_SSH_CONNECT_TIMEOUT_SECONDS:-30}"
DEPLOY_COMMAND_TIMEOUT_SECONDS="${DEPLOY_COMMAND_TIMEOUT_SECONDS:-900}"
DEPLOY_GIT_TIMEOUT_SECONDS="${DEPLOY_GIT_TIMEOUT_SECONDS:-120}"

if [[ -z "$RUN_WORKER_CONTROL_URL" ]]; then
  echo "RUN_WORKER_CONTROL_URL is required" >&2
  exit 2
fi
if [[ -z "$RUN_WORKER_TOKEN" ]]; then
  echo "RUN_WORKER_TOKEN is required" >&2
  exit 2
fi
if [[ ! -r "$SSH_KEY" ]]; then
  echo "SSH key is not readable: $SSH_KEY" >&2
  exit 2
fi
if [[ -n "$QWEN_SETTINGS_FILE" && ! -f "$QWEN_SETTINGS_FILE" ]]; then
  echo "QWEN_SETTINGS_FILE does not exist: $QWEN_SETTINGS_FILE" >&2
  exit 2
fi

shell_quote() {
  printf "%q" "$1"
}

DEPLOY_ID="$(date +%s)-$$-$RANDOM"
REMOTE_ENV_FILE="/root/.agentflow-worker-env-$DEPLOY_ID"
REMOTE_QWEN_SETTINGS_FILE="/root/.agentflow-qwen-settings-$DEPLOY_ID.json"

REMOTE_ENV=(
  "APP_DIR=$(shell_quote "$APP_DIR")"
  "STATE_DIR=$(shell_quote "$STATE_DIR")"
  "REPO_URL=$(shell_quote "$REPO_URL")"
  "REPO_REF=$(shell_quote "$REPO_REF")"
  "REPO_UPDATE=$(shell_quote "$REPO_UPDATE")"
  "NODE_PACKAGE=$(shell_quote "$NODE_PACKAGE")"
  "NODE_VERSION=$(shell_quote "$NODE_VERSION")"
  "HAS_QWEN_SETTINGS=$(shell_quote "$([[ -n "$QWEN_SETTINGS_FILE" ]] && echo 1 || echo 0)")"
  "QWEN_SETTINGS_REMOTE_FILE=$(shell_quote "$REMOTE_QWEN_SETTINGS_FILE")"
  "RUN_WORKER_CONTROL_URL=$(shell_quote "$RUN_WORKER_CONTROL_URL")"
  "RUN_WORKER_TOKEN=$(shell_quote "$RUN_WORKER_TOKEN")"
  "RUN_WORKER_ID=$(shell_quote "$RUN_WORKER_ID")"
  "RUN_WORKER_CAPACITY=$(shell_quote "$RUN_WORKER_CAPACITY")"
  "RUN_WORKER_LEASE_TTL_SECONDS=$(shell_quote "$RUN_WORKER_LEASE_TTL_SECONDS")"
  "RUN_WORKER_POLL_INTERVAL_SECONDS=$(shell_quote "$RUN_WORKER_POLL_INTERVAL_SECONDS")"
  "RUN_WORKER_HEARTBEAT_INTERVAL_SECONDS=$(shell_quote "$RUN_WORKER_HEARTBEAT_INTERVAL_SECONDS")"
  "RUN_WORKER_RUN_WAIT_TIMEOUT_SECONDS=$(shell_quote "$RUN_WORKER_RUN_WAIT_TIMEOUT_SECONDS")"
  "RUN_WORKER_METADATA_JSON=$(shell_quote "$RUN_WORKER_METADATA_JSON")"
  "QWEN_SERVE_URL=$(shell_quote "$QWEN_SERVE_URL")"
  "QWEN_SERVE_TOKEN=$(shell_quote "$QWEN_SERVE_TOKEN")"
  "QWEN_SERVE_ENV_FILE=$(shell_quote "$QWEN_SERVE_ENV_FILE")"
  "QWEN_MANAGED_SERVE=$(shell_quote "$QWEN_MANAGED_SERVE")"
  "QWEN_SERVE_HOST=$(shell_quote "$QWEN_SERVE_HOST")"
  "QWEN_SERVE_PORT=$(shell_quote "$QWEN_SERVE_PORT")"
  "QWEN_SERVE_WORKSPACE=$(shell_quote "$QWEN_SERVE_WORKSPACE")"
  "QWEN_SERVE_STARTUP_TIMEOUT_SECONDS=$(shell_quote "$QWEN_SERVE_STARTUP_TIMEOUT_SECONDS")"
  "DEPLOY_COMMAND_TIMEOUT_SECONDS=$(shell_quote "$DEPLOY_COMMAND_TIMEOUT_SECONDS")"
  "DEPLOY_GIT_TIMEOUT_SECONDS=$(shell_quote "$DEPLOY_GIT_TIMEOUT_SECONDS")"
)

SSH_OPTIONS=(
  -i "$SSH_KEY"
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout="$DEPLOY_SSH_CONNECT_TIMEOUT_SECONDS"
  -o ConnectionAttempts=1
)

umask 077
LOCAL_ENV_FILE="$(mktemp)"
cleanup_local_files() {
  rm -f "$LOCAL_ENV_FILE"
  ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" \
    "rm -f $(shell_quote "$REMOTE_ENV_FILE") $(shell_quote "$REMOTE_QWEN_SETTINGS_FILE")" \
    >/dev/null 2>&1 || true
}
trap cleanup_local_files EXIT
printf '%s\n' "${REMOTE_ENV[@]}" >"$LOCAL_ENV_FILE"
scp "${SSH_OPTIONS[@]}" "$LOCAL_ENV_FILE" "$SSH_TARGET:$REMOTE_ENV_FILE"

if [[ -n "$QWEN_SETTINGS_FILE" ]]; then
  scp \
    "${SSH_OPTIONS[@]}" \
    "$QWEN_SETTINGS_FILE" \
    "$SSH_TARGET:$REMOTE_QWEN_SETTINGS_FILE"
fi

REMOTE_BOOTSTRAP="set -a; source $(shell_quote "$REMOTE_ENV_FILE")"
REMOTE_BOOTSTRAP+="; rm -f $(shell_quote "$REMOTE_ENV_FILE")"
REMOTE_BOOTSTRAP+="; set +a; exec bash -s"
ssh \
  "${SSH_OPTIONS[@]}" \
  "$SSH_TARGET" \
  "bash -c $(shell_quote "$REMOTE_BOOTSTRAP")" <<'REMOTE'
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

log_step() {
  printf '[worker-deploy] %s\n' "$*"
}

run_timeout() {
  local label="$1"
  local timeout_seconds="$2"
  shift 2
  log_step "$label"
  timeout "$timeout_seconds" "$@"
}

node_package_name() {
  local package="$1"
  if [[ "$package" == @*/*@* ]]; then
    package="${package%@*}"
  elif [[ "$package" != @* && "$package" == *@* ]]; then
    package="${package%@*}"
  fi
  printf '%s\n' "$package"
}

remove_qwen_npm_staging_dirs() {
  local npm_root=""
  npm_root="$(npm root -g 2>/dev/null || true)"
  if [[ -n "$npm_root" && -d "$npm_root/@qwen-code" ]]; then
    find "$npm_root/@qwen-code" \
      -maxdepth 1 \
      -type d \
      -name '.qwen-code-*' \
      -exec rm -rf {} +
  fi
}

install_node_package() {
  local package="$1"
  local package_name=""
  local attempt=1
  local exit_code=0
  package_name="$(node_package_name "$package")"
  while (( attempt <= 3 )); do
    if run_timeout \
      "install node package $package attempt $attempt/3" \
      "$DEPLOY_COMMAND_TIMEOUT_SECONDS" \
      npm install -g "$package"; then
      return 0
    else
      exit_code=$?
    fi
    if (( attempt == 3 )); then
      return "$exit_code"
    fi
    log_step "clean npm install state for $package_name"
    remove_qwen_npm_staging_dirs
    npm uninstall -g "$package_name" || true
    npm cache verify || true
    attempt=$((attempt + 1))
  done
}

run_git_with_retry() {
  local label="$1"
  shift
  local attempt=1
  local exit_code=0
  while (( attempt <= 3 )); do
    if run_timeout \
      "$label attempt $attempt/3" \
      "$DEPLOY_GIT_TIMEOUT_SECONDS" \
      git -c http.version=HTTP/1.1 "$@"; then
      return 0
    else
      exit_code=$?
    fi
    if (( attempt == 3 )); then
      return "$exit_code"
    fi
    sleep $((attempt * 2))
    attempt=$((attempt + 1))
  done
}

if ! command -v git >/dev/null \
  || ! command -v python3 >/dev/null \
  || ! command -v curl >/dev/null \
  || ! command -v openssl >/dev/null \
  || ! command -v xz >/dev/null; then
  run_timeout "apt-get update" "$DEPLOY_COMMAND_TIMEOUT_SECONDS" apt-get update
  run_timeout \
    "install worker host packages" \
    "$DEPLOY_COMMAND_TIMEOUT_SECONDS" \
    apt-get install -y ca-certificates curl git openssl python3 xz-utils
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(`.`)[0]' 2>/dev/null || echo 0)"
if (( NODE_MAJOR < 22 )) || ! command -v npm >/dev/null; then
  case "$(uname -m)" in
    x86_64|amd64) NODE_ARCH=x64 ;;
    aarch64|arm64) NODE_ARCH=arm64 ;;
    *) echo "unsupported Node.js architecture: $(uname -m)" >&2; exit 2 ;;
  esac
  NODE_ARCHIVE="node-v$NODE_VERSION-linux-$NODE_ARCH.tar.xz"
  NODE_DOWNLOAD_ROOT="https://nodejs.org/dist/v$NODE_VERSION"
  NODE_DOWNLOAD_DIR="$(mktemp -d)"
  trap 'rm -rf "$NODE_DOWNLOAD_DIR"' EXIT
  run_timeout \
    "download Node.js $NODE_VERSION" \
    "$DEPLOY_COMMAND_TIMEOUT_SECONDS" \
    curl -fsSLo "$NODE_DOWNLOAD_DIR/$NODE_ARCHIVE" \
      "$NODE_DOWNLOAD_ROOT/$NODE_ARCHIVE"
  run_timeout \
    "download Node.js checksums" \
    "$DEPLOY_COMMAND_TIMEOUT_SECONDS" \
    curl -fsSLo "$NODE_DOWNLOAD_DIR/SHASUMS256.txt" \
      "$NODE_DOWNLOAD_ROOT/SHASUMS256.txt"
  NODE_EXPECTED_SHA="$(
    awk -v archive="$NODE_ARCHIVE" \
      '$2 == archive {print $1; exit}' \
      "$NODE_DOWNLOAD_DIR/SHASUMS256.txt"
  )"
  NODE_ACTUAL_SHA="$(sha256sum "$NODE_DOWNLOAD_DIR/$NODE_ARCHIVE" | awk '{print $1}')"
  if [[ -z "$NODE_EXPECTED_SHA" || "$NODE_EXPECTED_SHA" != "$NODE_ACTUAL_SHA" ]]; then
    echo "Node.js archive checksum verification failed" >&2
    exit 3
  fi
  run_timeout \
    "install Node.js $NODE_VERSION" \
    "$DEPLOY_COMMAND_TIMEOUT_SECONDS" \
    tar -xJf "$NODE_DOWNLOAD_DIR/$NODE_ARCHIVE" \
      --strip-components=1 \
      -C /usr/local
  rm -rf "$NODE_DOWNLOAD_DIR"
  trap - EXIT
  hash -r
fi
NODE_MAJOR="$(node -p 'process.versions.node.split(`.`)[0]' 2>/dev/null || echo 0)"
if (( NODE_MAJOR < 22 )); then
  echo "Node.js 22 or newer is required; found $(node --version 2>/dev/null || echo missing)" >&2
  exit 1
fi

install_node_package "$NODE_PACKAGE"
QWEN_BIN="$(command -v qwen || true)"
if [[ -z "$QWEN_BIN" ]]; then
  echo "qwen executable was not found after installing $NODE_PACKAGE" >&2
  exit 1
fi

if ! id cloudagents >/dev/null 2>&1; then
  log_step "create cloudagents user"
  useradd --system --create-home --shell /usr/sbin/nologin cloudagents
fi

mkdir -p "$APP_DIR" "$STATE_DIR/artifacts" "$STATE_DIR/workspace"
chown -R cloudagents:cloudagents "$STATE_DIR"
install -d -m 700 -o cloudagents -g cloudagents /home/cloudagents/.qwen
if [[ "$HAS_QWEN_SETTINGS" == "1" ]]; then
  install -m 600 -o cloudagents -g cloudagents \
    "$QWEN_SETTINGS_REMOTE_FILE" \
    /home/cloudagents/.qwen/settings.json
  rm -f "$QWEN_SETTINGS_REMOTE_FILE"
fi

if [[ "$REPO_UPDATE" != "0" && "$REPO_UPDATE" != "1" ]]; then
  echo "REPO_UPDATE must be 0 or 1" >&2
  exit 2
fi

if [[ ! -d "$APP_DIR/.git" ]] \
  || ! git -C "$APP_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  rm -rf "$APP_DIR"
  mkdir -p "$(dirname "$APP_DIR")"
  clone_attempt=1
  clone_exit_code=0
  while (( clone_attempt <= 3 )); do
    rm -rf "$APP_DIR"
    if run_timeout \
      "clone runtime repository attempt $clone_attempt/3" \
      "$DEPLOY_GIT_TIMEOUT_SECONDS" \
      git -c http.version=HTTP/1.1 clone \
        --depth 1 \
        --branch "$REPO_REF" \
        --single-branch \
        "$REPO_URL" \
        "$APP_DIR"; then
      break
    else
      clone_exit_code=$?
    fi
    if (( clone_attempt == 3 )); then
      exit "$clone_exit_code"
    fi
    sleep $((clone_attempt * 2))
    clone_attempt=$((clone_attempt + 1))
  done
elif [[ "$REPO_UPDATE" == "1" ]]; then
  run_git_with_retry \
    "fetch runtime repository" \
    -C "$APP_DIR" fetch --depth 1 origin "$REPO_REF"
  run_timeout \
    "reset runtime repository" \
    "$DEPLOY_COMMAND_TIMEOUT_SECONDS" \
    git -C "$APP_DIR" reset --hard "origin/$REPO_REF"
else
  log_step "reuse existing runtime repository without network update"
fi

if [[ -z "$RUN_WORKER_ID" ]]; then
  RUN_WORKER_ID="$(hostname -f 2>/dev/null || hostname)"
fi

read_env_value() {
  local file="$1"
  local key="$2"
  awk -v key="$key" 'index($0, key "=") == 1 {print substr($0, length(key) + 2); exit}' "$file"
}

if [[ -n "$QWEN_SERVE_ENV_FILE" ]]; then
  if [[ ! -r "$QWEN_SERVE_ENV_FILE" ]]; then
    echo "QWEN_SERVE_ENV_FILE is not readable: $QWEN_SERVE_ENV_FILE" >&2
    exit 2
  fi
  if [[ -z "$QWEN_SERVE_URL" ]]; then
    QWEN_SERVE_URL="$(read_env_value "$QWEN_SERVE_ENV_FILE" QWEN_SERVE_URL)"
  fi
  if [[ -z "$QWEN_SERVE_TOKEN" ]]; then
    QWEN_SERVE_TOKEN="$(read_env_value "$QWEN_SERVE_ENV_FILE" QWEN_SERVE_TOKEN)"
  fi
fi

case "$QWEN_MANAGED_SERVE" in
  auto)
    if [[ -n "$QWEN_SERVE_URL" ]]; then
      QWEN_MANAGED_SERVE=0
    else
      QWEN_MANAGED_SERVE=1
    fi
    ;;
  0|1) ;;
  *)
    echo "QWEN_MANAGED_SERVE must be auto, 0, or 1" >&2
    exit 2
    ;;
esac

if [[ "$QWEN_MANAGED_SERVE" == "1" ]]; then
  QWEN_SERVE_URL="http://$QWEN_SERVE_HOST:$QWEN_SERVE_PORT"
  if [[ -z "$QWEN_SERVE_TOKEN" ]]; then
    QWEN_SERVE_TOKEN="$(openssl rand -hex 32)"
  fi
  install -d -m 750 -o cloudagents -g cloudagents "$QWEN_SERVE_WORKSPACE"
  cat > /etc/cloud-agents-qwen.env <<EOF
QWEN_SERVER_TOKEN=$QWEN_SERVE_TOKEN
HOME=/home/cloudagents
EOF
  chmod 600 /etc/cloud-agents-qwen.env
  cat > /etc/systemd/system/cloud-agents-qwen.service <<EOF
[Unit]
Description=AgentFlow managed qwen-code daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cloudagents
Group=cloudagents
WorkingDirectory=$QWEN_SERVE_WORKSPACE
EnvironmentFile=/etc/cloud-agents-qwen.env
ExecStart=$QWEN_BIN serve \
  --hostname $QWEN_SERVE_HOST \
  --port $QWEN_SERVE_PORT \
  --workspace $QWEN_SERVE_WORKSPACE \
  --max-sessions 1 \
  --max-total-sessions 1 \
  --no-web \
  --require-auth
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$STATE_DIR /home/cloudagents/.qwen
CPUAccounting=true
CPUQuota=100%
MemoryAccounting=true
MemoryMax=768M
TasksAccounting=true
TasksMax=256

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now cloud-agents-qwen
  systemctl restart cloud-agents-qwen
fi

if [[ -z "$QWEN_SERVE_URL" ]]; then
  echo "QWEN_SERVE_URL is required when managed qwen serve is disabled" >&2
  exit 2
fi

log_step "wait for qwen serve health"
QWEN_HEALTH_DEADLINE=$((SECONDS + QWEN_SERVE_STARTUP_TIMEOUT_SECONDS))
while true; do
  if [[ -n "$QWEN_SERVE_TOKEN" ]]; then
    if curl -fsS --connect-timeout 2 --max-time 5 \
      -H "Authorization: Bearer $QWEN_SERVE_TOKEN" \
      "$QWEN_SERVE_URL/health" >/dev/null; then
      break
    fi
  elif curl -fsS --connect-timeout 2 --max-time 5 \
    "$QWEN_SERVE_URL/health" >/dev/null; then
    break
  fi
  if (( SECONDS >= QWEN_HEALTH_DEADLINE )); then
    echo "qwen serve did not become healthy at $QWEN_SERVE_URL" >&2
    if [[ "$QWEN_MANAGED_SERVE" == "1" ]]; then
      systemctl --no-pager --full status cloud-agents-qwen || true
      journalctl -u cloud-agents-qwen -n 120 --no-pager || true
    fi
    exit 3
  fi
  sleep 1
done

cat > /etc/cloud-agents-worker.env <<EOF
RUN_WORKER_CONTROL_URL=$RUN_WORKER_CONTROL_URL
RUN_WORKER_TOKEN=$RUN_WORKER_TOKEN
RUN_WORKER_ID=$RUN_WORKER_ID
RUN_WORKER_CAPACITY=$RUN_WORKER_CAPACITY
RUN_WORKER_LEASE_TTL_SECONDS=$RUN_WORKER_LEASE_TTL_SECONDS
RUN_WORKER_POLL_INTERVAL_SECONDS=$RUN_WORKER_POLL_INTERVAL_SECONDS
RUN_WORKER_HEARTBEAT_INTERVAL_SECONDS=$RUN_WORKER_HEARTBEAT_INTERVAL_SECONDS
RUN_WORKER_RUN_WAIT_TIMEOUT_SECONDS=$RUN_WORKER_RUN_WAIT_TIMEOUT_SECONDS
RUN_WORKER_ARTIFACT_ROOT=$STATE_DIR/artifacts
RUN_WORKER_METADATA_JSON=$RUN_WORKER_METADATA_JSON
QWEN_SERVE_URL=$QWEN_SERVE_URL
QWEN_SERVE_TOKEN=$QWEN_SERVE_TOKEN
EOF
chmod 600 /etc/cloud-agents-worker.env

cp "$APP_DIR/deploy/systemd/cloud-agents-worker.service" /etc/systemd/system/
install -d -m 755 /etc/systemd/system/cloud-agents-worker.service.d
cat > /etc/systemd/system/cloud-agents-worker.service.d/paths.conf <<EOF
[Service]
WorkingDirectory=$APP_DIR
Environment=PYTHONPATH=$APP_DIR/runtime
ReadWritePaths=$STATE_DIR
EOF
systemctl daemon-reload
systemctl enable --now cloud-agents-worker
systemctl restart cloud-agents-worker
WORKER_DEADLINE=$((SECONDS + 45))
while ! systemctl is-active --quiet cloud-agents-worker; do
  if (( SECONDS >= WORKER_DEADLINE )); then
    break
  fi
  sleep 1
done
if ! systemctl --no-pager --full status cloud-agents-worker; then
  journalctl -u cloud-agents-worker -n 120 --no-pager || true
  exit 3
fi

log_step "wait for worker heartbeat registration"
WORKER_DEADLINE=$((SECONDS + 45))
while true; do
  if curl -fsS --connect-timeout 2 --max-time 5 \
    -H "Authorization: Bearer $RUN_WORKER_TOKEN" \
    "$RUN_WORKER_CONTROL_URL/workers/$RUN_WORKER_ID" >/dev/null; then
    break
  fi
  if (( SECONDS >= WORKER_DEADLINE )); then
    echo "worker heartbeat was not visible through $RUN_WORKER_CONTROL_URL" >&2
    journalctl -u cloud-agents-worker -n 120 --no-pager || true
    exit 3
  fi
  sleep 1
done

echo "worker $RUN_WORKER_ID registered through $RUN_WORKER_CONTROL_URL"
echo "qwen $(qwen --version) ready through $QWEN_SERVE_URL"
echo "repository $REPO_REF deployed at $(git -C "$APP_DIR" rev-parse --short HEAD)"
REMOTE
