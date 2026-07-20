#!/bin/zsh
set -euo pipefail

: "${AFLOW_REPO_ROOT:?AFLOW_REPO_ROOT is required}"
: "${AFLOW_WORKER_ENV_FILE:?AFLOW_WORKER_ENV_FILE is required}"

set -a
source "$AFLOW_WORKER_ENV_FILE"
set +a

cd "$AFLOW_REPO_ROOT"
exec "${PYTHON_BIN:-python3}" -m runtime.cloud_agents_runtime.worker
