# 单 Agent 基座选型

> 结论：短期先直接部署 Qwen Code `qwen serve` 作为第一版 worker，并在外层构建云端 runtime；但开源项目的执行器接口必须面向任意 ACP-compatible Agent，而不是绑定 Qwen Code。不要一开始深 fork，也不要从头实现完整 coding agent。

## 三种路线对比

| 路线 | 优点 | 风险 | 建议 |
| --- | --- | --- | --- |
| 直接部署 Qwen Code | 最快验证能力；已有 subagent、daemon、JSONL、sandbox、权限、MCP 等能力 | 受限于原项目接口和实验性特性 | POC 和 MVP 首选 |
| ACP-compatible adapter | 可接入 Claude Code、Codex、OpenCode、自研 worker | 需要定义 canonical events 和能力协商 | 开源兼容主线 |
| Fork Qwen Code | 可改深层事件、权限、沙箱、模型和 daemon 行为 | 维护成本高，容易跟不上上游 | 等 runtime 边界清晰后再做 |
| 从头实现 | 完全可控，架构纯净 | 成本极高，会重复踩工具调度、权限、上下文、恢复坑 | 不建议 |

## 为什么优先 Qwen Code

Qwen Code 已经覆盖很多 Cloud Agent worker 的关键能力：

- headless、daemon、SDK、IM bot 等多入口。
- `qwen serve` 提供本地 HTTP + SSE daemon，支持 session、prompt、events、permission mediation。
- AgentCore 抽出 subagent 共享推理循环。
- background subagent 有 JSONL transcript 和 meta sidecar。
- 支持 background resume/revive。
- 有 cron/wakeup、任务协调、worktree isolation、permission manager、tool scheduler。
- 支持 MCP、SubAgents、Agent Teams、Dynamic Workflows、Sandbox、Git Worktrees。

关键本地文件：

- `/Users/chigao/Documents/codebase/github/qwen-code/docs/users/qwen-serve.md`
- `/Users/chigao/Documents/codebase/github/qwen-code/docs/developers/daemon/01-architecture.md`
- `/Users/chigao/Documents/codebase/github/qwen-code/docs/developers/daemon/19-observability.md`
- `/Users/chigao/Documents/codebase/github/qwen-code/docs/design/daemon-acp-http/README.md`
- `/Users/chigao/Documents/codebase/github/qwen-code/packages/acp-bridge/src/bridge.ts`

## 其他项目的启发

### Claude Code

Claude Code 的架构重点是工具优先、AsyncGenerator query loop、权限检查、并行/串行工具调度、自动压缩、hooks 和 subagent/worktree/remote runner。这说明 coding agent 的稳定性来自完整 harness，而不是模型调用包装。

参考：

- Claude Code 官方文档、headless/SDK 能力和公开架构资料。

### Gemini CLI

Gemini CLI 的 subagents 体现了 specialist + independent context window 的模式；remote agents 支持 A2A；checkpointing 用 shadow git repo 保存文件和对话状态。这对本项目的多 Agent 和恢复设计很有参考价值。

参考：

- `/Users/chigao/Documents/codebase/github/gemini-cli/docs/core/subagents.md`
- `/Users/chigao/Documents/codebase/github/gemini-cli/docs/core/remote-agents.md`
- `/Users/chigao/Documents/codebase/github/gemini-cli/docs/cli/checkpointing.md`

### OpenCode

OpenCode 对 Agent permission、session、subagent child session 和强类型 session events 的设计，非常适合作为本项目事件模型和任务状态模型参考。

参考：

- `/Users/chigao/Documents/codebase/github/opencode/packages/opencode/src/agent/agent.ts`
- `/Users/chigao/Documents/codebase/github/opencode/packages/opencode/src/v2/session.ts`
- `/Users/chigao/Documents/codebase/github/opencode/packages/opencode/src/v2/session-event.ts`

## 推荐演进路径

### 阶段 1：黑盒 worker

把 Qwen Code 当成外部进程或容器运行：

```text
Run Manager -> Worker Supervisor -> qwen-code container/process
```

只要求它：

- 接受 prompt。
- 输出事件。
- 执行工具。
- 生成 JSONL、diff、final report。
- 能被取消。

本阶段尽量不改 Qwen Code 源码，但 adapter 接口不要暴露 qwen 私有概念。

### 阶段 2：ACP-compatible adapter

写一层 adapter，把 qwen-code 的事件转成内部 canonical events，同时把控制面抽象成 ACP-compatible 操作：

```text
native agent protocol -> adapter -> canonical events
ACP stdio / ACP Streamable HTTP -> adapter -> Run Manager
```

好处：

- 将来可以替换为 Claude Code、Codex、OpenCode、Gemini CLI 或自研 worker。
- 内部 UI 和 orchestration 不被单一项目格式锁死。
- 可以逐步补全缺失事件。

### 阶段 3：轻 fork

当黑盒方式不满足时，只 fork 明确边界：

- 事件输出格式。
- permission policy。
- sandbox launcher。
- transcript schema。
- daemon session scope。
- model proxy 接入。

避免改：

- model reasoning loop 的大结构。
- tool scheduler 的复杂调度逻辑。
- 上下文压缩和恢复逻辑。

### 阶段 4：抽取 worker SDK

如果长期维护需要，可以把 Qwen Code 中稳定模块抽成内部 worker SDK：

- AgentCore wrapper。
- Tool scheduler adapter。
- Permission bridge。
- Transcript writer。
- Sandbox bridge。

这时你已经知道哪些抽象是真需求，而不是设计阶段想象出来的接口。

## 不建议从头实现的原因

coding agent 的复杂度主要不在“调用模型”，而在这些细节：

- 模型工具调用和 streaming 的边界状态。
- function call 未闭合时的恢复。
- 工具并发和串行化。
- shell 输出截断、持久化和增量更新。
- 权限继承和冒泡。
- plan mode、auto mode、non-interactive mode 的差异。
- context compaction。
- loop detection。
- worktree 路径翻译。
- background agent resume。
- MCP 工具发现和失败处理。
- telemetry、成本和错误归因。

这些都是现成项目已经大量处理过的问题。从头写会很干净，但很慢，而且早期很难稳定。

## MVP 接口契约

外层 Run Manager 不应依赖 Qwen Code 内部类型，只依赖 worker 契约。远期这套契约应尽量贴近 ACP：

```text
start(run_spec) -> run_handle
send_input(run_id, message)
resolve_permission(run_id, permission_id, decision)
cancel(run_id)
stream_events(run_id) -> events
collect_artifacts(run_id) -> artifact_refs
```

`run_spec` 包含：

- repo/workspace。
- prompt。
- agent type。
- model config。
- sandbox policy。
- tool policy。
- timeout。
- artifact paths。

`event` 至少包含：

- run status。
- assistant message。
- tool call。
- tool result。
- permission request/resolution。
- artifact created。
- error。
- heartbeat。

## 决策

短期：

- 直接部署 Qwen Code。
- 用 Docker 包起来。
- 用 adapter 采集事件和 artifact。
- 外层做 Run Manager、权限、事件和沙箱。

中期：

- 只 fork 必须改的边界。
- 与上游保持小 diff。
- 引入 OpenCode 风格强类型事件。
- 引入 Gemini/Claude 风格 checkpoint/worktree/subagent 经验。

长期：

- 形成自己的 Cloud Agent Runtime。
- worker 可以是 Qwen Code，也可以是 Claude Code、Codex、OpenCode 或其他 ACP-compatible agent。
- 多 Agent 编排基于内部 run/event/artifact 模型，而不是绑定某个 CLI。
