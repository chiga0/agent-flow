#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${AGENTFLOW_DOCKER_ENV:-$ROOT_DIR/.env.docker}"
ACTION="${1:-up}"

COMPOSE=(
  docker compose
  --env-file "$ENV_FILE"
  -f "$ROOT_DIR/deploy/docker-compose.runtime.yml"
  -f "$ROOT_DIR/deploy/docker-compose.qwen.yml"
)

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE; run: python3 scripts/init_docker_env.py" >&2
  exit 2
fi

case "$ACTION" in
  build)
    "${COMPOSE[@]}" build runtime
    ;;
  up)
    "${COMPOSE[@]}" up -d --build --wait --wait-timeout 120 runtime
    ;;
  up-no-build)
    "${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 120 runtime
    ;;
  down)
    "${COMPOSE[@]}" down
    ;;
  status)
    "${COMPOSE[@]}" ps
    ;;
  logs)
    "${COMPOSE[@]}" logs --tail=200 runtime
    ;;
  smoke)
    "${COMPOSE[@]}" exec -T runtime sh -lc '
      python3 scripts/smoke_v2_control_plane.py \
        --base-url http://127.0.0.1:8765 \
        --email "$RUN_MANAGER_BOOTSTRAP_EMAIL" \
        --password "$RUN_MANAGER_BOOTSTRAP_PASSWORD" \
        --adapter fake \
        --mode auto \
        --timeout 30
    '
    ;;
  qwen-smoke)
    "${COMPOSE[@]}" exec -T runtime sh -lc '
      python3 scripts/smoke_v2_control_plane.py \
        --base-url http://127.0.0.1:8765 \
        --email "$RUN_MANAGER_BOOTSTRAP_EMAIL" \
        --password "$RUN_MANAGER_BOOTSTRAP_PASSWORD" \
        --adapter auto \
        --execution-unit-id local-dev \
        --expect-execution-mode real-cli \
        --goal "只读检查当前工作区根目录并用一句中文确认 Docker 中的真实 Qwen 可用，不要修改文件。" \
        --mode auto \
        --timeout 600
    '
    ;;
  *)
    echo "usage: $0 {build|up|up-no-build|down|status|logs|smoke|qwen-smoke}" >&2
    exit 2
    ;;
esac
