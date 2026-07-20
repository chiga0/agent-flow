# 快速开始

这篇文档帮助你从零完成第一个可审计任务。当前推荐路径是先在本机或 NAS 跑通整套应用，再按需要增加公网入口或云端执行资源。

## 0. 推荐启动链路

先安装 Git、Docker 和 Docker Compose v2，然后执行：

```bash
git clone https://github.com/chiga0/aflow.git
cd aflow
make local-up
make local-demo
```

`make local-up` 会生成私有 `.env.local`、构建 Runtime/Web、注册同机执行单元并跑 smoke；`make local-demo` 会运行多角色复杂案例并验证 Chat/WebShell、DAG、事件、产物、评估和审计。终端会给出访问地址与登录邮箱，随机密码只保存在权限为 `0600` 的 `.env.local`。

通过后再选择下一步：

- 只在本机使用：保持 `RUNTIME_BIND=127.0.0.1`。
- NAS/局域网使用：绑定 `0.0.0.0`，只通过防火墙或私有 VPN 开放。
- 单 VPS：使用部署 workflow 或 2C2G profile，并将并发限制为 1。
- 本机+云端：先把 VPS 用作公网入口；需要真实跨机 V2 执行时，先阅读[场景化部署与验收](deployment-scenarios.md)中的现行边界。
- 启用真实 Agent：按 [Agent CLI 配置](agent-adapters.md)逐个验证，不要一次打开全部 adapter。

## 1. 访问入口

Client 面向任务发起者：

```text
https://<你的域名>/cloud-agents/#/
```

Admin 面向 owner、operator、auditor：

```text
https://<你的域名>/cloud-agents/#/admin
```

登录使用部署时配置的本地邮箱账户：

| 字段 | 来源 |
| --- | --- |
| 邮箱 | `RUN_MANAGER_BOOTSTRAP_EMAIL` 或 GitHub Secret `RUNTIME_AUTH_EMAIL` |
| 密码 | `RUN_MANAGER_BOOTSTRAP_PASSWORD` 或 GitHub Secret `RUNTIME_AUTH_PASSWORD` |

如果兼容部署没有配置 `RUNTIME_AUTH_PASSWORD`，部署 workflow 会兼容使用 `RUNTIME_BASIC_AUTH_PASSWORD` 作为登录密码。不要把密码写入仓库、文档或聊天记录。

## 2. 创建第一个任务

第一次验证请用 `fake` adapter，先确认平台链路健康：

1. 打开 Client。
2. 在任务输入框写入：`请回复 OK，并说明当前任务链路可用。`
3. Adapter 选择 `fake`。
4. 提交任务。
5. 进入 Task Detail，确认能看到 `Agent Chat`、状态、Workflow、Canonical Events、Artifacts。
6. 下载或预览产物，确认任务完成。

fake 任务通过后，再尝试 `qwen` 或其他真实 adapter。真实 adapter 依赖 CLI 命令、模型配置、机器资源、workspace 隔离和权限策略，排障复杂度明显更高。

### 真实仓库任务

真实代码任务不要让 Runtime 容器直接访问整个 NAS。保持 Runtime 运行，再在 Mac 主机启动容量为 1 的 Worker，并只允许项目根目录：

```bash
export RUN_WORKER_CONTROL_URL=http://127.0.0.1:8765
export RUN_WORKER_TOKEN="$(awk -F= '$1=="RUN_MANAGER_TOKEN"{print $2}' .env.local)"
export RUN_WORKER_ID=mac-local-worker
export RUN_WORKER_CAPACITY=1
export RUN_WORKER_ARTIFACT_ROOT="$PWD/.aflow/worker-data"
export V2_WORKER_ADAPTERS=qwen
export V2_ENABLE_REAL_CLI_ADAPTERS=1
export V2_QWEN_CODE_COMMAND=qwen
export V2_WORKSPACE_ROOTS=/Volumes/AIProjects
export V2_AGENT_TIMEOUT_SECONDS=3600
export V2_WORKSPACE_TEST_TIMEOUT_SECONDS=1800
export V2_MAX_COMMAND_OUTPUT_BYTES=262144
export V2_MAX_COMMAND_EVENT_LINES=5000
export V2_MAX_PATCH_BYTES=1048576
export V2_WORKSPACE_RETENTION_SECONDS=604800
export V2_BRANCH_RETENTION_SECONDS=2592000
PYTHONPATH=runtime python3 -m cloud_agents_runtime.worker
```

Client 中选择 `Single`、对应 Agent 和明确的 Mac/NAS Execution Unit，填写 Repository path、Git ref 和项目原有测试命令。仓库任务不会在 Worker 失联时漂移到另一台机器。Worker 会创建独立 `aflow/*` 分支和 worktree；成功标准是 Chat 有实时输出，Artifacts 同时存在测试结果、patch 和 commit，且源检出目录没有变化。不要在这条链路通过前启用多 Agent或 HA。

长期运行时先把上述变量保存到权限为 `600` 的 env 文件，再安装 macOS 服务：

```bash
chmod 600 /absolute/path/to/aflow-worker.env
python3 scripts/install_worker_launchd.py \
  --repo "$PWD" \
  --env-file /absolute/path/to/aflow-worker.env
launchctl print "gui/$(id -u)/com.aflow.worker"
tail -f .aflow/logs/worker.log .aflow/logs/worker.error.log
# 停止并卸载：
python3 scripts/install_worker_launchd.py --uninstall
```

## 3. 真实 Agent 验证顺序

建议按这个顺序逐步打开能力：

| 顺序 | 验证项 | 成功标准 |
| --- | --- | --- |
| 1 | fake task | Task completed，事件和产物完整 |
| 2 | Admin overview | 队列、Workflow、HA、Channel 状态可读 |
| 3 | Execution Unit | 至少一个 active unit 或 worker 心跳正常 |
| 4 | qwen task | Agent Chat 有真实输出，artifact 中有日志或报告 |
| 5 | IM Channel | 平台消息能创建 task，出站消息可审计 |
| 6 | Retry/Replay | 失败任务可以重试，历史事件可以回放 |

## 4. 普通用户应该看什么

普通用户只需要理解四个区域：

| 区域 | 作用 |
| --- | --- |
| New Task | 描述目标、选择简单/复杂任务、选择 adapter |
| Recent Tasks | 找到自己最近提交的任务 |
| Agent Chat | 实时看 Agent 输出、工具调用和需要你处理的动作 |
| Artifacts / Result | 查看最终结果、报告、日志和审计材料 |

不要从 Admin 的 Run、Worker、Executor 开始学习。那些是运维和审计视角。

## 5. 管理员上线检查

管理员部署后至少检查：

1. [Admin 管理指南](admin-guide.md) 中的 Overview、Execution Units、Channels、Tenants、HA。
2. [执行单元注册与调度](execution-units.md) 中的 unit/worker 注册。
3. [IM 机器人接入](channel-integrations.md) 中的签名校验和回调代理。
4. [部署指南](deployment-runbook.md) 中的 smoke、备份、监控和资源建议。

2C2G 机器建议只跑低并发控制面或单 worker。真实 qwen、Playwright、前端构建、Docker build 和多任务并发不要挤在同一台 2C2G 上。
