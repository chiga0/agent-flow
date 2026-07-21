# 事件溯源与回放

aflow 的任务状态应由事件流重建，而不是只依赖某个运行中进程的内存状态。这是客户端崩溃不影响后台任务、失败可审计、历史可回放的基础。

## 1. 事件类型

核心事件包括：

| 类型 | 含义 |
| --- | --- |
| `task.created` | 任务创建 |
| `user.message` | 用户输入或 follow-up |
| `plan.created` | 编排计划生成 |
| `agent_task.started` | 子 Agent 开始 |
| `agent.message` | Agent 输出 |
| `agent.thought` | CLI 对外提供的思考/推理摘要 |
| `tool.started/updated/completed/failed` | 工具、Skill 或 MCP 调用生命周期 |
| `shell.output` | Shell/验证命令输出 |
| `permission.requested` | 请求人工审批 |
| `permission.resolved` | 审批结果 |
| `permission.applied` | Worker 已成功应用审批结果 |
| `artifact.created` | 产物生成 |
| `evaluation.completed` | 评估完成 |
| `task.failed` | 任务失败 |
| `task.completed` | 任务完成 |

CLI 私有事件先进入 adapter，再转换为这些标准事件。

Worker 只能写入受控白名单中的过程事件，不能直接伪造 `task.completed`、`task.failed` 等权威终态。控制面按 `task + agent_task + attempt + source_event_id` 去重，并在同一任务内分配严格递增 sequence；重连重发不会在 Chat 中产生重复块。Task 与 Agent 状态使用显式迁移表，终态由控制面完成/失败接口统一提交。

## 2. Projection

同一条事件流可以投影为不同视图：

| Projection | 给谁看 |
| --- | --- |
| Agent Chat | 普通用户 |
| Workflow/DAG | 专业用户和管理员 |
| Artifact list | 用户和 auditor |
| Admin health | operator |
| Audit bundle | auditor 和 owner |
| WebShell DaemonEvent | Client Chat 组件 |

这样可以避免把底层 JSONL 直接暴露给普通用户，同时保留完整审计证据。

## 3. Replay

Replay 用于复盘任务，不等于重新执行真实 CLI。

Replay 应能回答：

- 当时用户输入了什么。
- Orchestrator 生成了什么计划。
- 每个 Agent 收到什么上下文。
- 哪一步失败或等待审批。
- 产物和评估结果是什么。

重新执行应使用 Retry，并明确记录新的 attempt。

## 4. Retry

Retry 必须记录：

- 原任务 ID。
- retry reason。
- retry policy。
- 新 attempt ID。
- 是否复用 workspace。
- 是否复用 artifacts。

不可幂等操作需要人工确认或由 policy 禁止自动重试。

## 5. 存储建议

单机 profile 可以把事件和 artifact 放在本地状态目录。HA profile 应使用：

- Postgres 保存任务、事件索引和配置。
- NAS/共享卷/对象存储保存 artifact。
- Redis 或 Temporal 管理队列和 workflow 状态。
- 定期备份 DB、artifact 和配置。
