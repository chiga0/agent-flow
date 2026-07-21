# Qwen WebShell Chat 渲染

aflow 的 Client 直接使用 `@qwen-code/web-shell` 的 Workspace/Session 组件展示 Agent 过程，但内部事件源仍保持统一 canonical events。这样可以复用 qwen-code 的交互体验，又不会把平台锁死在某一个 CLI 的私有事件格式上。

## 1. 设计边界

| 层 | 职责 |
| --- | --- |
| Adapter | 把 qwen/codex/claude/opencode 输出转为标准事件 |
| Event Store | 保存 canonical events |
| Projection | 把标准事件转成 WebShell/DaemonEvent |
| Client | 用 Qwen WebShell 渲染 Agent Chat、思考摘要、工具/MCP、Shell、权限和错误 |

Client 不直接读取 CLI 原始 stdout 作为唯一事实源。脱敏、限长后的原生事件保存在 canonical event 的 `native_event` 中，投影层只把稳定字段发送给 WebShell。

## 2. 为什么需要 Projection

不同 CLI 的事件格式不同：

- qwen-code 有 daemon/session 事件。
- Codex CLI 有自己的流式输出和工具事件。
- Claude Code 和 OpenCode 也有不同结构。

Projection 让这些事件在用户侧呈现为统一体验：

- 用户消息。
- Agent 输出。
- CLI/模型公开的思考摘要。
- 工具调用。
- Skill 与 MCP 调用。
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

当前主链路使用带 sequence 续传的 SSE，轮询只作为断线降级：

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
- Codex/OpenCode task 能展示消息、工具和公开的 reasoning 摘要。
- MCP/Skill 调用按 WebShell tool block 展示，并保留开始、更新和终态。
- follow-up 能写入事件流。
- 权限请求能在 Chat 中被发现。
- failed task 有错误提示和 artifact 链接。
- 页面刷新后能从事件流恢复聊天内容。
- 同一 attempt 的重复源事件不会重复显示，新的 retry attempt 可独立记录。

“完整过程”指底层 Agent 实际发出的消息、reasoning 摘要、工具、MCP、Skill、Shell、权限、文件交付与终态。模型或 CLI 没有对外提供的隐藏 chain-of-thought 不在协议能力范围内；平台不会尝试绕过模型安全边界获取它。
