# 架构走读：一次任务如何完成

这篇从真实流程解释 AgentFlow：用户发起任务，系统编排 Agent，执行单元运行 CLI，最后产生产物和审计材料。

## 1. 用户提交任务

用户在 Client 输入目标，例如：

```text
审计当前项目的部署链路，输出风险、修复顺序和验收命令。
```

Client 调用 Task API。控制面会保存：

- 用户身份和租户。
- 任务目标。
- adapter 偏好。
- source channel。
- 初始事件。

## 2. Orchestrator 生成计划

控制面判断任务复杂度：

- 简单任务：生成单 Agent 执行计划。
- 复杂任务：生成 DAG，包含 planner、worker、reviewer、finalizer 等角色。

每个子 Agent 都必须有：

- role。
- context。
- goal。
- artifact contract。
- evaluation criteria。

## 3. Workflow 持久化执行

Workflow 负责让任务不会因为浏览器关闭或 worker 短暂失败而丢失。

单机部署默认使用内置 durable engine。HA profile 可以使用 Redis 和 Temporal 来获得更强的队列、重试、超时和恢复能力。

## 4. 调度执行单元

Scheduler 根据以下信息选择 Execution Unit：

- unit status。
- adapters。
- labels。
- CPU/内存/磁盘等资源。
- capacity 和 active count。
- tenant policy。
- workspace 或 Docker/ECS/NAS 能力。

如果没有可用 unit，Task 会保持 queued，并在 Admin 中显示排队原因。

## 5. Adapter 启动真实 CLI

执行单元通过 adapter 启动真实 Agent CLI：

| Adapter | 命令示例 |
| --- | --- |
| qwen | `qwen` |
| codex | `codex` |
| claude | `claude` |
| opencode | `opencode` |

adapter 会把 CLI 输出转换为统一事件：Agent message、tool call、permission request、shell output、artifact、failed/completed。

## 6. Client 实时观察

Task Detail 把事件投影成几个用户可理解区域：

- Agent Chat：默认主区域，展示 WebShell/DaemonEvent。
- Workflow：展示 DAG 当前状态。
- Artifacts：展示结果和产物。
- Evaluations：展示产物是否达标。
- Canonical Events：保留底层审计事件。

用户可以在任务仍可交互时发送 follow-up。追加消息同样会写入事件流。

## 7. 结果、评估和审计

任务完成后，系统保留：

- final artifact。
- 子任务 artifact。
- evaluation。
- replay snapshot。
- audit bundle。

失败时，管理员可以根据错误类型、executor stderr、unit 状态和事件流决定 retry、replay、迁移执行单元或调整 adapter 配置。

## 8. Channel 入口

Web、移动端、钉钉、飞书、企业微信最终都会进入同一套 Task API。不同入口只影响 source、identity mapping 和通知方式，不应绕过 RBAC、权限审批和审计。
