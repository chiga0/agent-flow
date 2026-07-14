# 自我部署

AgentFlow 当前最推荐的部署形态是：GitHub Actions 负责 CI 和部署，一台 VPS 运行 runtime + Nginx + qwen foundation。资源紧张时，再把控制面和 worker 拆开。

## 部署形态选择

| 形态 | 适合谁 | 说明 |
| --- | --- | --- |
| GitHub Actions + VPS | 最推荐 | push 到 main 后自动测试、构建、部署、验收 |
| 本地电脑/NAS 控制面 + VPS worker | 长任务和低配 VPS | 控制面更稳，VPS 只做执行单元或公网入口 |
| 纯本地开发 | 开发者 | 用于改代码、跑测试、验证 UI |

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

CI 应继续跑在 GitHub-hosted runner 或本机/NAS/更大构建机上。2C2G 部署后只跑 smoke、health、monitor 和可选 qwen acceptance。当前 CI 已包含 V2 control-plane smoke；部署 workflow 也会在 VPS 本地补跑 V2 smoke。

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
| `RUNTIME_BASIC_AUTH_USER` | 兼容 | 旧 Basic Auth 用户名；新部署不推荐依赖 |
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
| `RUNTIME_APP_DIR` | `/opt/agent-research` | VPS 上的应用目录 |
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
3. 跑 V2 control-plane smoke。
4. 跑 web lint、单测、构建和 E2E。
5. 写入临时 SSH key 和 qwen settings。
6. 执行 `scripts/deploy_runtime_vps.sh` 部署 VPS。
7. 在 VPS 本地跑 fake run smoke 和 V2 smoke。
8. 校验 VPS 上 git revision 等于当前 commit。
9. 通过公网入口登录并检查 `/health`。

`Runtime Monitor` 会每 15 分钟检查公网入口，也会在部署成功后自动运行。

## 本地电脑/NAS 控制面 + VPS worker

当 VPS 资源紧张时，推荐拆成：

- 本地电脑/NAS/大 VPS：AgentFlow Runtime + Web + SQLite/artifact。
- 小 VPS：worker 或公网 Nginx 边缘。

完整教程见：[本地电脑或 NAS 作为 AgentFlow 主控的部署教程](implementation/local-nas-control-plane-deployment.md)。

关键原则：

- 控制面负责状态、审计、Web、队列。
- worker 只负责执行任务。
- worker 使用 scoped API token，不使用 master token。
- qwen worker 从 `capacity=1` 开始。

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

V2 smoke：

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
