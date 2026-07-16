# AgentFlow 从部署到可用产品的完整教程

这篇文档按真实使用顺序组织：先选部署拓扑，再启动控制面，注册执行单元，接入 IM 机器人，最后创建第一个任务并做运维检查。第一次部署建议完整走一遍，不要只看单个命令片段。

## 1. 你会部署哪些组件

```mermaid
flowchart LR
  Browser["用户浏览器 / 移动端 Web"] --> Runtime["AgentFlow Runtime + Web"]
  IM["钉钉 / 飞书 / 企微"] --> Edge["公网入口 / 签名校验代理"]
  Edge --> Runtime
  Runtime --> State["SQLite 或 Postgres<br/>事件 / 配置 / 审计"]
  Runtime --> Artifacts["Artifact 存储"]
  Runtime --> Queue["队列 / Workflow Engine"]
  Queue --> WorkerA["本机 / NAS worker"]
  Queue --> WorkerB["Docker / ECS worker"]
  WorkerA --> CLIA["qwen-code / codex / claude / opencode"]
  WorkerB --> CLIB["qwen-code / codex / claude / opencode"]
```

核心职责：

| 组件 | 职责 | 低配建议 |
| --- | --- | --- |
| Runtime | 登录、Client/Admin 页面、任务 API、审计、队列控制 | 2C2G 可跑低并发 |
| 数据库 | 存任务、事件、租户、Channel、执行单元配置 | 单机先 SQLite，HA 用 Postgres |
| 队列/Workflow | 支撑后台任务、重试、durable workflow | 单机内置队列，HA 用 Redis/Temporal profile |
| Worker | 主动领任务、拉起 CLI Agent、上传事件和产物 | 2C2G worker 固定 `capacity=1` |
| 执行单元 | worker 的产品视图，可代表本机 workspace、Docker、ECS、NAS | 先注册一台 NAS 或本机 |
| Channel | Web、移动端 Web、钉钉、飞书、企微入口 | 生产建议加签名校验代理 |

## 2. 选择部署拓扑

| 拓扑 | 适合场景 | 推荐程度 |
| --- | --- | --- |
| 本机/NAS 控制面 + 2C2G VPS worker | 你有稳定本机或 NAS，希望低配 VPS 不被打满 | 最推荐 |
| 单台 2C2G VPS | 演示、低并发、fake smoke、轻量 qwen | 可用但余量小 |
| HA profile: Postgres + Redis + Temporal + 多 worker | 团队长期使用、需要备份恢复和水平扩展 | 生产方向 |

2C2G 可以承载控制面低并发访问、fake smoke 和 1 个轻量 worker；不适合同时承担前端构建、Playwright、qwen 多并发、Docker build 和公网管理台。CI 应跑在 GitHub-hosted runner、本机、NAS 或更大的构建机上。

## 3. 快速路径 A：本机或 NAS 作为控制面

### 3.1 安装依赖

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip nodejs npm nginx
```

需要真实 qwen 时再安装：

```bash
npm install -g @qwen-code/qwen-code
qwen --version
```

### 3.2 拉取代码并构建 Web

```bash
sudo mkdir -p /opt/agentflow
sudo chown "$USER":"$USER" /opt/agentflow
git clone https://github.com/chiga0/agent-flow.git /opt/agentflow
cd /opt/agentflow/web
npm ci
npm run build
```

运行目录建议固定为 `/opt/agentflow`，后续 systemd、worker 和部署脚本都更好维护。

### 3.3 创建运行目录和密钥

```bash
sudo mkdir -p /var/lib/agentflow-runtime
sudo chown "$USER":"$USER" /var/lib/agentflow-runtime

python3 - <<'PY'
import secrets
print("RUN_MANAGER_TOKEN=" + secrets.token_urlsafe(32))
print("RUN_MANAGER_BOOTSTRAP_PASSWORD=" + secrets.token_urlsafe(18))
print("RUN_MANAGER_SESSION_SECRET=" + secrets.token_urlsafe(32))
PY
```

写入 `/etc/agentflow-runtime.env`：

```bash
sudo tee /etc/agentflow-runtime.env >/dev/null <<'EOF'
RUN_MANAGER_HOST=127.0.0.1
RUN_MANAGER_PORT=8765
RUN_MANAGER_ARTIFACT_ROOT=/var/lib/agentflow-runtime
RUN_MANAGER_TOKEN=replace-with-generated-token
RUN_MANAGER_BOOTSTRAP_EMAIL=owner@example.com
RUN_MANAGER_BOOTSTRAP_PASSWORD=replace-with-generated-password
RUN_MANAGER_BOOTSTRAP_NAME=Owner
RUN_MANAGER_SESSION_SECRET=replace-with-generated-session-secret
RUN_MANAGER_WORKER_CAPACITY=0
RUN_MANAGER_REMOTE_WORKERS_ENABLED=true
QWEN_COMMAND=qwen
EOF
```

`RUN_MANAGER_WORKER_CAPACITY=0` 表示控制面先不抢任务，只负责调度。等远程 worker 接通后再决定是否让本机也执行任务。

### 3.4 创建 systemd 服务

```bash
sudo tee /etc/systemd/system/agentflow-runtime.service >/dev/null <<'EOF'
[Unit]
Description=AgentFlow Runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/agentflow
EnvironmentFile=/etc/agentflow-runtime.env
Environment=PYTHONPATH=/opt/agentflow/runtime
ExecStart=/usr/bin/python3 -m cloud_agents_runtime --host 127.0.0.1 --port 8765 --artifact-root /var/lib/agentflow-runtime --protect-health
Restart=always
RestartSec=5
NoNewPrivileges=true
LimitNOFILE=65535
CPUAccounting=true
CPUQuota=150%
MemoryAccounting=true
MemoryMax=1536M
TasksAccounting=true
TasksMax=1024

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now agentflow-runtime
sudo systemctl status agentflow-runtime --no-pager
```

### 3.5 验证控制面

```bash
curl -s http://127.0.0.1:8765/health

cd /opt/agentflow
PYTHONPATH=runtime python3 scripts/smoke_v2_control_plane.py \
  --base-url http://127.0.0.1:8765 \
  --email owner@example.com \
  --password "$(awk -F= '$1=="RUN_MANAGER_BOOTSTRAP_PASSWORD"{print $2}' /etc/agentflow-runtime.env)" \
  --timeout 10
```

浏览器入口：

```text
http://127.0.0.1:8765/#/
http://127.0.0.1:8765/#/admin
```

登录账号来自环境变量：

| 字段 | 来源 |
| --- | --- |
| 邮箱 | `RUN_MANAGER_BOOTSTRAP_EMAIL` |
| 密码 | `RUN_MANAGER_BOOTSTRAP_PASSWORD` |

## 4. 快速路径 B：单台 2C2G VPS

单台 2C2G 可以跑通产品体验，但需要收紧并发和资源限制：

```bash
cp deploy/runtime.2c2g.env.example .env
python3 - <<'PY' >> .env
import secrets
print("RUN_MANAGER_TOKEN=" + secrets.token_urlsafe(32))
print("RUNTIME_BOOTSTRAP_PASSWORD=" + secrets.token_urlsafe(18))
print("RUN_MANAGER_SESSION_SECRET=" + secrets.token_urlsafe(32))
PY
docker compose -f deploy/docker-compose.runtime.yml up -d --build
```

建议保持：

| 配置 | 建议值 |
| --- | --- |
| `RUN_MANAGER_WORKER_CAPACITY` | `1` |
| `RUNTIME_MEMORY_LIMIT` | `768m` 到 `1536m` |
| `QWEN_CONTAINER_MEMORY_MB` | `768` 到 `1024` |
| `QWEN_EXECUTOR_STRATEGY` | 先 `shared` |

部署后只跑 smoke 和健康检查，不要在这台机器上跑完整 CI、Playwright browser install 或多并发 qwen。

## 5. 快速路径 C：HA profile

HA profile 适合团队长期运行，目标是 Postgres 持久化、Redis 队列、Temporal workflow、多 worker 水平扩展和备份恢复。

```bash
cp deploy/runtime.ha.env.example .env
python3 - <<'PY' >> .env
import secrets
print("RUN_MANAGER_TOKEN=" + secrets.token_urlsafe(32))
print("RUNTIME_BOOTSTRAP_PASSWORD=" + secrets.token_urlsafe(18))
print("RUN_MANAGER_SESSION_SECRET=" + secrets.token_urlsafe(32))
print("POSTGRES_PASSWORD=" + secrets.token_urlsafe(24))
print("RUN_WORKER_TOKEN=" + secrets.token_urlsafe(32))
PY
```

补齐 `.env`：

```bash
POSTGRES_DB=agentflow
POSTGRES_USER=agentflow
V2_DATABASE_URL=postgresql://agentflow:${POSTGRES_PASSWORD}@postgres:5432/agentflow
V2_QUEUE_URL=redis://redis:6379/0
V2_WORKFLOW_ENGINE=temporal
TEMPORAL_TASK_QUEUE=agentflow-v2
V2_WORKER_REPLICAS=2
V2_WORKER_CONCURRENCY=2
V2_BACKUP_ENABLED=1
V2_BACKUP_TARGET=/data/backups
```

`V2_` 前缀是当前实现的环境变量兼容命名，不代表部署时还需要选择产品版本。

启动：

```bash
docker compose --env-file .env -f deploy/docker-compose.ha.yml up -d --build
docker compose --env-file .env -f deploy/docker-compose.ha.yml ps
```

2C2G VPS 不建议直接跑这个 profile。更稳的方式是把 HA profile 放在 NAS、工作站或更大云主机上，2C2G VPS 只做公网边缘或 `capacity=1` worker。

## 6. 注册执行单元

执行单元有两种注册路径：

| 路径 | 用途 | 入口 |
| --- | --- | --- |
| Execution Unit Registry | 描述 Docker、ECS、NAS、本机 workspace 等能力，供编排和调度选择 | Admin -> Execution Units |
| Remote Worker Registration | 生成 worker 专用 token 和部署命令，让一台机器主动连回控制面领任务 | Admin -> Units |

### 6.1 用环境变量发现执行单元

在控制面 `.env` 或 systemd env 中设置：

```bash
V2_EXECUTION_UNITS_JSON='[
  {
    "unit_id": "nas-home",
    "kind": "nas",
    "status": "active",
    "labels": {"region": "home", "tier": "stable"},
    "resources": {"cpu": 4, "memory_mb": 8192},
    "adapters": ["fake", "qwen", "codex"],
    "features": ["workspace", "artifacts", "long-running"]
  },
  {
    "unit_id": "ecs-hk-2c2g",
    "kind": "ecs",
    "status": "active",
    "labels": {"region": "hk", "size": "2c2g"},
    "resources": {"cpu": 2, "memory_mb": 2048},
    "adapters": ["fake", "qwen"],
    "features": ["remote-worker"]
  }
]'
```

`V2_EXECUTION_UNITS_JSON` 是当前实现沿用的变量名。文档和产品视角统一称为 Execution Unit Registry。

重启 runtime 后，在 Admin -> Execution Units 点击 Discover，或者调用：

```bash
curl -X POST "$BASE_URL/v2/admin/execution-units/discover" \
  -H "Authorization: Bearer $RUN_MANAGER_TOKEN"
```

### 6.2 直接注册一个执行单元

```bash
curl -X POST "$BASE_URL/v2/admin/execution-units" \
  -H "Authorization: Bearer $RUN_MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "unit_id": "docker-local",
    "kind": "docker",
    "status": "active",
    "labels": {"host": "nas-01"},
    "resources": {"cpu": 2, "memory_mb": 4096},
    "adapters": ["fake", "qwen", "opencode"],
    "features": ["workspace", "artifacts"]
  }'
```

### 6.3 注册远程 worker

1. 打开 Admin -> Units。
2. 点击生成 worker registration。
3. 选择“本地源码安装”或“无源码安装”命令。
4. 替换 worker IP、SSH key 和 worker id。
5. 在 worker 机器上执行部署命令。
6. 回到 Units 页面确认 heartbeat、capacity、资源水位正常。

worker 的关键环境变量：

```bash
RUN_WORKER_CONTROL_URL=https://agentflow.example.com/cloud-agents-worker
RUN_WORKER_TOKEN=replace-with-worker-scoped-token
RUN_WORKER_ID=ecs-hk-1
RUN_WORKER_CAPACITY=1
RUN_WORKER_ARTIFACT_ROOT=/var/lib/cloud-agents-worker/artifacts
RUN_WORKER_METADATA_JSON={"region":"hk","labels":{"tier":"sandbox"}}
```

2C2G worker 保持 `RUN_WORKER_CAPACITY=1`，真实 qwen 任务先串行验证。

## 7. 接入钉钉、飞书、企业微信机器人

详细步骤见 [钉钉、飞书、企业微信机器人接入](channel-integrations.md)。第一次接入按这个顺序：

1. 在平台群里创建自定义机器人，复制 webhook URL。
2. 在 AgentFlow Admin -> Channels 选择平台，填入 `webhook_url` 和 `callback_token`。
3. 发送测试消息，确认群里能收到 AgentFlow 通知。
4. 如果要让群消息创建 AgentFlow 任务，把平台回调先接到边缘签名校验代理，再由代理转发到 `/v2/channels/{platform}/webhook`。
5. 在 Channel Messages 查看入站、出站消息留痕。

当前 Runtime 已真实支持通用入站和出站协议；平台原生 HMAC/加签校验建议放在边缘代理中完成，再转成 `x-agentflow-channel-token` 传给 Runtime。

## 8. 创建第一个任务

1. 打开 `http://127.0.0.1:8765/#/`。
2. 登录 owner 账号。
3. 在 Client 首页输入目标，例如“生成本周运维巡检报告，包含异常项和修复建议”。
4. 先选择 fake 或 auto，验证链路。
5. 再选择 qwen、codex、claude 或 opencode adapter 做真实执行。
6. 打开任务详情页，观察 Chat、DAG、事件流、产物、评估和重试入口。
7. 完成后下载 artifact 和 audit bundle。

如果任务排队，去 Admin -> Units 或 Admin -> Execution Units 看是否有 active worker、容量是否已满、最近 heartbeat 是否过期。

## 9. Admin 日常操作

| 页面 | 做什么 |
| --- | --- |
| Overview | 看系统健康、任务状态、HA profile、队列水位 |
| Execution Units | 注册/发现 Docker、ECS、NAS、本机 workspace 能力 |
| Channels | 配置 Web、mobile、钉钉、飞书、企微收发 |
| Tenants | 管租户配置、用户、RBAC 策略 |
| Workflow Engines | 看内置/Temporal workflow engine 配置 |
| Units | 管远程 worker、生成 registration、drain/resume/retry |
| Access | 管 token 和权限 |
| Operations | 看备份、成本、运行时状态和审计视图 |

## 10. 备份与恢复

单机 profile 需要备份：

| 目录/文件 | 含义 |
| --- | --- |
| `RUN_MANAGER_ARTIFACT_ROOT` | artifact、SQLite、审计包、运行时状态 |
| `/etc/agentflow-runtime.env` | owner、token、session secret、资源限制 |
| `/opt/agentflow` | 当前代码版本，可用 git 恢复 |

HA profile 需要备份：

| 对象 | 建议 |
| --- | --- |
| Postgres | 定时 `pg_dump` 或卷快照 |
| Redis | 开启 AOF，保留 `redis-data` 卷 |
| Artifact | 备份 `runtime-artifacts` 卷或挂载到 NAS |
| Backup target | 备份 `/data/backups` 或对应宿主机目录 |
| Env secrets | 加密保存 `.env`，不要提交到 git |

恢复顺序：

1. 恢复代码到同一 commit。
2. 恢复 env secrets。
3. 恢复数据库和 artifact 目录。
4. 启动 runtime。
5. 启动 worker。
6. 跑 health 和 control-plane smoke。
7. 用一条 fake task 验证 Client、Admin、artifact 和 audit。

## 11. 最小验收清单

部署完成后至少确认：

| 检查项 | 通过标准 |
| --- | --- |
| 登录 | owner 邮箱密码可以进入 Client 和 Admin |
| Health | `/health` 返回正常 |
| Control-plane smoke | `scripts/smoke_v2_control_plane.py` 完成 |
| fake task | Client 创建任务后能完成并产生事件 |
| 执行单元 | Admin 能看到至少 1 个 active unit 或 worker |
| IM 出站 | 目标群能收到测试消息 |
| IM 入站 | 测试 curl 能创建 channel task |
| artifact | 任务详情能预览或下载产物 |
| audit | 能下载事件、diagnostics、audit bundle |
| 备份 | 知道数据库、artifact、env secret 存在哪里 |

## 12. 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 登录失败 | `RUN_MANAGER_BOOTSTRAP_EMAIL`、`RUN_MANAGER_BOOTSTRAP_PASSWORD`、session secret |
| 页面能开但任务一直 queued | worker heartbeat、capacity、drain 状态、执行单元 labels |
| qwen 失败 | qwen 是否安装、settings 是否可用、机器内存、审批是否卡住 |
| IM 出站失败 | `webhook_url` 是否正确、平台安全设置、Runtime 日志中的 HTTP error |
| IM 入站 403 | `callback_token` 和 `x-agentflow-channel-token` 是否一致 |
| 2C2G 卡顿 | 降到 fake 或 qwen 串行，关闭本机构建，把 worker 拆到 NAS/本机 |
