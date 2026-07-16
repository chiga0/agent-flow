# ACP、A2A 与 MCP 协议选型

AgentFlow 的协议分层目标是：内部执行可控，外部互操作开放，工具接入不和 Agent 通信混在一起。

## 1. 结论

| 协议 | 在 AgentFlow 中的位置 | 说明 |
| --- | --- | --- |
| ACP | 内部 Agent CLI 控制协议候选 | 适合把 qwen/codex/claude/opencode 包装成统一 adapter |
| A2A | 外部 Agent 互操作协议候选 | 适合和外部 Agent 平台互相发现、发任务、取状态 |
| MCP | 工具和上下文接入协议 | 适合让 Agent 使用外部工具、数据源和上下文 |

内部执行不要直接暴露成 A2A。A2A 不关心 workspace、权限审批、执行单元资源、CLI 日志和 artifact 生命周期；这些仍应由 AgentFlow 控制面管理。

## 2. 内部 adapter contract

所有真实 Agent CLI 进入 AgentFlow 时，应被转换为统一事件：

- `agent.message`
- `agent.tool_call`
- `permission.requested`
- `permission.resolved`
- `artifact.created`
- `task.failed`
- `task.completed`

无论底层是 qwen-code、Codex CLI、Claude Code 还是 OpenCode，Client 都只消费标准化事件和 WebShell 投影。

## 3. ACP 适合做什么

ACP 更适合承担“控制一个本地或远程 Agent runtime”的职责：

- 启动 session。
- 发送用户消息。
- 接收流式消息和工具调用。
- 取消任务。
- 恢复 session。
- 查询状态。

AgentFlow 可以在 adapter 层兼容 ACP transport，但控制面的权限、审计、artifact、retry/replay 仍由 AgentFlow 负责。

## 4. A2A 适合做什么

A2A 更适合外部互操作：

- 暴露 Agent capability。
- 接收外部 task。
- 返回 task 状态和产物。
- 让其他平台把 AgentFlow 当成一个可调用 Agent。

A2A Gateway 必须经过租户、RBAC、Channel policy 和审计，不能绕过 Task API 直接调执行单元。

## 5. MCP 适合做什么

MCP 是工具层协议，不替代 Agent-to-Agent 或 Agent runtime 控制协议。

适合接入：

- 文件系统工具。
- 数据库。
- SaaS API。
- 文档、知识库和搜索。
- 企业内部工具。

MCP server 的凭据、权限和审计应归属于租户或执行策略。

## 6. 当前推荐

1. AgentFlow 内部继续使用统一 adapter 事件模型。
2. qwen/codex/claude/opencode adapter 可以逐步适配 ACP。
3. 外部开放互操作时，通过 A2A Gateway 进入 Task API。
4. 工具和上下文通过 MCP 接入，但由租户 policy 控制。
5. Client 永远消费 AgentFlow 标准事件和 WebShell 投影，不直接绑定某个 CLI 的私有协议。
