# Qwen WebShell Chat 渲染

AgentFlow 的 Client 使用 WebShell 风格的聊天区域展示 Agent 过程，但内部事件源仍保持统一 canonical events。这样可以复用 qwen-code 的交互体验，又不会把平台锁死在某一个 CLI 的私有事件格式上。

## 1. 设计边界

| 层 | 职责 |
| --- | --- |
| Adapter | 把 qwen/codex/claude/opencode 输出转为标准事件 |
| Event Store | 保存 canonical events |
| Projection | 把标准事件转成 WebShell/DaemonEvent |
| Client | 渲染 Agent Chat、工具调用、权限和错误 |

Client 不直接读取 CLI 原始 stdout 作为唯一事实源。stdout/stderr 会作为 artifact 或诊断材料保留。

## 2. 为什么需要 Projection

不同 CLI 的事件格式不同：

- qwen-code 有 daemon/session 事件。
- Codex CLI 有自己的流式输出和工具事件。
- Claude Code 和 OpenCode 也有不同结构。

Projection 让这些事件在用户侧呈现为统一体验：

- 用户消息。
- Agent 输出。
- 工具调用。
- Shell 输出。
- 权限请求。
- Warning/Error。
- 完成状态。

## 3. Task Detail 中的展示

Task Detail 的 Agent Chat 是默认主区域：

- 顶部显示 WebShell/DaemonEvent 标签。
- 中间展示 Agent 输出和工具摘要。
- 底部提供 follow-up 输入框。
- 没有事件时显示明确空状态。
- Canonical Events 放在后面作为审计视图。

## 4. 实时传输

当前可以使用轮询拉取事件。更好的生产体验是：

| 方式 | 用途 |
| --- | --- |
| SSE | Agent 输出、工具事件、状态更新 |
| WebSocket | 双向交互、权限处理、取消、follow-up |
| Polling | 降级路径 |

无论使用哪种传输，服务端都应从事件流恢复状态，不能依赖浏览器连接保持任务存活。

## 5. 验收标准

WebShell Chat 达标需要：

- fake task 能展示完整过程。
- qwen task 能展示真实输出。
- follow-up 能写入事件流。
- 权限请求能在 Chat 中被发现。
- failed task 有错误提示和 artifact 链接。
- 页面刷新后能从事件流恢复聊天内容。
