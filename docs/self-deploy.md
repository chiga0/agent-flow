# 自我部署

aflow 当前最推荐的部署形态是：先在本机或 NAS 用 Docker Compose 跑通 Runtime、Web 和同机执行单元，再按需要接入公网入口。单 VPS 更适合演示或低并发；GitHub Actions 负责质量门禁和可选部署，不应成为本地首次上手的前置依赖。

## 部署形态选择

| 形态 | 适合谁 | 说明 |
| --- | --- | --- |
| 本机/NAS 一体化 | 最推荐 | `make local-up && make local-demo`，依赖最少、反馈最快 |
| GitHub Actions + VPS | 演示/低并发 | push main 后测试、构建、部署；依赖稳定 SSH 和公网资源 |
| 本机/NAS + 云端 | 推荐 | 云端只承担公网入口；Mac Worker 在 NAS 仓库的隔离 worktree 中执行 |

如果你只有一台 2C2G VPS，可以先跑通，但不要期待它同时承载 qwen、构建、多个 run 和公网管理台都很稳定。正式使用建议至少把 worker 拆出去，或者把控制面放到更稳定的机器。

## 2C2G 与 CI 边界

2C2G 可以承载：

- runtime control plane 的低并发访问。
- SQLite artifact/event 存储。
- fake adapter smoke。
- `capacity=1` 的轻量 worker。
- 作为公网 Nginx/TLS/Tunnel 边缘。

2C2G 不应承载：

- GitHub Actions 同等完整 CI，包括前端 build、coverage、Playwright browser install/E2E。
- 控制面 + qwen executor + 多 worker 并发。
- 长时间大仓库构建、Docker image build 和 qwen deep acceptance 同时运行。

CI 应继续跑在 GitHub-hosted runner 或本机/NAS/更大构建机上。2C2G 部署后只跑 smoke、health 和可选 Agent acceptance。当前 CI 已包含 control-plane smoke；部署 workflow 也会在 VPS 本地补跑同一套 smoke。自动 `Runtime Monitor` workflow 已关闭，`scripts/monitor_runtime.py` 仅保留为人工或外部监控系统调用的验收工具。

推荐资源策略：

| 场景 | 建议 |
| --- | --- |
| 单台 2C2G VPS | 使用 `deploy/runtime.2c2g.env.example`，`RUN_MANAGER_WORKER_CAPACITY=1`，不要跑完整 CI |
| 本机/NAS 主控 | 使用 `deploy/runtime.local-nas.env.example`，控制面 `capacity=0`，小 VPS 只做 worker |
| qwen 真实执行 | 先 fake smoke，再 qwen；2C2G 上 qwen 并发固定为 1 |
| 生产访问 | 本机/NAS 主控 + Cloudflare Tunnel/Tailscale/VPS Nginx 边缘 |

## GitHub Actions + VPS

这是当前项目最方便的部署路径：提交到 `main` 后，`Deploy Runtime` workflow 会运行测试、构建前端、SSH 到 VPS、更新代码、重启服务，并做 smoke test。

### 需要的 Repository Secrets

| Secret | 必填 | 含义 |
| --- | --- | --- |
| `RUNTIME_SSH_TARGET` | 是 | SSH 登录目标，例如 `root@47.243.94.91` |
| `RUNTIME_SSH_KEY` | 是 | 登录 VPS 的私钥文件内容，不是文件路径 |
| `RUNTIME_PUBLIC_HOST` | 是 | 公网 IP 或 host，例如 `47.243.94.91` |
| `RUNTIME_PUBLIC_DOMAIN` | 建议 | 域名，例如 `doubaofans.site`，部署脚本会配置 Nginx server_name |
| `RUNTIME_AUTH_EMAIL` | 是 | Web 管理台 owner 账户邮箱 |
| `RUNTIME_AUTH_PASSWORD` | 建议 | Web 管理台 owner 账户密码 |
| `RUNTIME_BASIC_AUTH_PASSWORD` | 兼容 | 如果没配 `RUNTIME_AUTH_PASSWORD`，会作为登录密码 fallback |
| `RUNTIME_BASIC_AUTH_USER` | 兼容 | 兼容 Basic Auth 用户名；新部署不推荐依赖 |
| `QWEN_SETTINGS_JSON` | qwen 需要 | qwen CLI settings JSON 内容 |

`RUNTIME_SSH_KEY` 要填私钥内容，例如：

```bash
cat /Users/chigao/Documents/works/ecs/aliyun-hongkong.pem
```

不要填 `/Users/.../aliyun-hongkong.pem` 这个本地路径。GitHub Actions 跑在云端，读不到你的本地文件。

### 需要的 Repository Variables

| Variable | 推荐值 | 含义 |
| --- | --- | --- |
| `RUNTIME_DEPLOY_ENABLED` | `1` | 允许 push main 自动部署 |
| `RUNTIME_APP_DIR` | `/opt/agentflow` | VPS 上的应用目录 |
| `RUNTIME_STATE_DIR` | `/var/lib/cloud-agents-runtime` | artifact、SQLite、backup 等状态目录 |
| `QWEN_EXECUTOR_STRATEGY` | `shared` | qwen executor 策略，低配机器先用 shared |

其他 CPU、内存、retention、container 变量可以之后按需配置。第一次部署不要把变量面铺得太大。

### 部署后如何访问

如果配置了域名：

```text
https://<RUNTIME_PUBLIC_DOMAIN>/cloud-agents/
```

如果只配置 IP：

```text
http://<RUNTIME_PUBLIC_HOST>/cloud-agents/
```

登录：

- email = `RUNTIME_AUTH_EMAIL`
- password = `RUNTIME_AUTH_PASSWORD`，没有则使用 `RUNTIME_BASIC_AUTH_PASSWORD`

### CI 会做什么

`Deploy Runtime` 主要步骤：

1. 校验必填 secrets。
2. 跑 runtime 编译、测试和覆盖率门禁。
3. 跑 control-plane smoke。
4. 跑 web lint、单测、构建和 E2E。
5. 写入临时 SSH key 和 qwen settings。
6. 执行 `scripts/deploy_runtime_vps.sh` 部署 VPS。
7. 在 VPS 本地跑 fake task smoke 和 control-plane smoke。
8. 校验 VPS 上 git revision 等于当前 commit。
9. 通过公网入口登录并检查 `/health`。

仓库不再定时运行 `Runtime Monitor`，避免持续 CI 消耗和真实 Agent 调用。部署后的健康检查由部署 workflow 完成；需要深度检查时手工执行 `scripts/monitor_runtime.py`，生产告警应交给独立监控系统。

## 本地电脑/NAS + 云端入口

当 VPS 资源紧张时，当前推荐拆成：

- 本地电脑/NAS/大 VPS：aflow Runtime + Web + SQLite/artifact。
- 小 VPS：公网 Nginx、TLS、Tunnel 或私网边缘。

现行 `/v2/tasks` 可显式绑定 Mac Remote Worker，并在 `V2_WORKSPACE_ROOTS` 允许的真实仓库上创建隔离 worktree，回传实时事件、测试结果、patch 和 commit。真实仓库任务强制 Single 模式、验证命令和真实 CLI，且禁止跨 Worker 漂移。完整边界与验收证据见[场景化部署与验收](deployment-scenarios.md)。

完整教程见：[本地电脑或 NAS 作为 aflow 主控的部署教程](implementation/local-nas-control-plane-deployment.md)。

如果你需要从 0 部署到可用产品，包括执行单元注册、IM 机器人接入、首个任务验收和备份恢复，请优先看：[aflow 从部署到可用产品的完整教程](deployment-runbook.md)。

关键原则：

- 控制面负责状态、审计、Web、队列。
- 云端入口不保存 Runtime master token，也不能绕过登录。
- Runtime 端口只通过防火墙、VPN 或 Tunnel 暴露。
- 上线前必须用目标仓库验证领取、worktree 隔离、事件、测试、patch/commit、取消和断线恢复。

## 纯本地开发

文档站：

```bash
python3 -m pip install -r requirements.txt
mkdocs serve
```

Runtime：

```bash
RUN_MANAGER_BOOTSTRAP_EMAIL=owner@example.com \
RUN_MANAGER_BOOTSTRAP_PASSWORD=secret \
PYTHONPATH=runtime \
python3 -m cloud_agents_runtime --host 127.0.0.1 --port 8765
```

Web：

```bash
cd web
npm ci
npm run dev
```

测试：

```bash
python3 -m unittest discover -s runtime/tests
cd web && npm run test
```

Control-plane smoke：

```bash
PYTHONPATH=runtime python3 scripts/smoke_v2_control_plane.py --timeout 10
PYTHONPATH=runtime python3 scripts/smoke_v2_control_plane.py \
  --base-url http://127.0.0.1:8765 \
  --email owner@example.com \
  --password secret \
  --timeout 10
```

## qwen 验收

先确认 fake run 正常，再跑 qwen：

```bash
python3 scripts/validate_qwen_mission.py \
  --base-url http://127.0.0.1:8765 \
  --token "$RUN_MANAGER_TOKEN" \
  --validate-single-run \
  --expect-executor-strategy shared \
  --timeout 600
```

qwen 失败时不要立刻判断平台坏了。先看 qwen settings、executor stderr、机器资源、权限审批和 executor strategy。
