# aflow

aflow 是一个可自托管的长期运行 Agent 平台。用户在 Client 端提交任务，系统负责编排 Agent、调度执行单元、保存过程事件、生成产物，并让管理员在 Admin 端完成运维、审计、租户配置和用户管理。

当前文档只描述现行产品形态。历史控制台、早期路线图和过期方案文档已经从文档导航中移除；代码中的 `/v2/...` API 名称仅作为后端接口命名保留，不再代表一个需要用户选择的产品版本。

## 先读什么

第一次上手建议按这个顺序：

1. [快速开始](getting-started.md)：用本机或 NAS 两条命令完成首个可审计任务。
2. [场景化部署与验收](deployment-scenarios.md)：按单 VPS、本机/NAS、本机+云端选择拓扑和验收门禁。
3. [Agent CLI 配置](agent-adapters.md)：启用并验证 qwen-code、Codex、OpenCode 等真实 CLI。
4. [核心概念](concepts.md)：理解 Task、Agent、Workflow、Execution Unit、Channel、Artifact、Audit。
5. [Client 使用指南](user-guide.md)：普通用户如何创建任务、追踪 Agent Chat、查看 DAG、下载产物。
6. [Admin 管理指南](admin-guide.md)：管理员如何管理租户、用户、执行单元、Channel、HA 和审计。
7. [执行单元注册与调度](execution-units.md)：接入本机 workspace、Docker、ECS、NAS 或远程 worker。
8. [架构总览](architecture.md)：从系统设计角度理解分层、现行执行边界和可靠性。
9. [排障手册](troubleshooting.md)：登录、任务卡住、CLI 失败、worker stale、部署失败时从这里查。

## 当前可用边界

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Client 工作台 | 可用 | 任务创建、任务列表、任务详情、Agent Chat、Workflow、Artifact、Retry、Replay |
| Admin 管理台 | 可用 | Overview、Execution Units、Channels、Tenants、RBAC、HA、Workflow 状态 |
| 真实 Agent adapter | 可用 | 支持 fake/qwen/codex/claude/opencode 统一 adapter；真实 CLI 需要在部署环境启用并安装命令 |
| qwen WebShell 投影 | 可用 | Task Detail 已把 WebShell/DaemonEvent 聊天区域作为核心区域展示 |
| IM Channel | 可用基础链路 | 支持平台配置、出站 webhook、入站 webhook 和消息审计；生产建议加边缘签名校验代理 |
| 执行单元 | 可用 | 支持环境发现、Admin 注册、V2 Remote Worker lease、隔离执行、实时回传、取消/审批/重试 |
| HA profile | 可验证 | Postgres、Redis、Temporal、多 worker、备份配置、Compose CI 和并发压测已具备；控制面多副本仍待共享 Postgres 领域存储迁移 |
| 商业级开放 SaaS | 仍需审慎 | SSO、邮件验证、计费、细粒度租户隔离、对象存储和更完整合规控制仍需继续建设 |

## 本地预览

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

浏览器打开：

```text
http://127.0.0.1:8765/#/
http://127.0.0.1:8765/#/admin
```
