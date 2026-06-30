# 事件溯源、JSONL 与回放

> 结论：JSONL 是一种事件或 transcript 的存储格式；事件溯源是一种系统建模方法。Qwen Code 的 JSONL 可以支持恢复和部分复现，但如果想完整复现用户场景，还必须记录 workspace、配置、工具输出、权限决策、模型输出和运行环境。

## 事件溯源是什么

事件溯源的核心不是“把日志写成 JSONL”，而是：

1. 系统状态由 append-only 事件推导出来。
2. 每个事件代表已经发生的事实。
3. 当前状态可以通过重放事件重建。
4. 审计、调试、恢复、回放都基于同一条事实链。

示例事件：

```json
{"type":"run.created","run_id":"run_1","agent":"qwen-code","created_at":"2026-06-30T10:00:00Z"}
{"type":"step.started","run_id":"run_1","step_id":"step_1","kind":"model_turn"}
{"type":"tool.called","run_id":"run_1","tool_call_id":"tool_1","tool":"shell","input_ref":"artifact://input/tool_1.json"}
{"type":"permission.requested","run_id":"run_1","permission_id":"perm_1","tool_call_id":"tool_1"}
{"type":"permission.approved","run_id":"run_1","permission_id":"perm_1","decider":"user_1"}
{"type":"tool.succeeded","run_id":"run_1","tool_call_id":"tool_1","output_ref":"artifact://output/tool_1.json"}
{"type":"run.completed","run_id":"run_1","status":"succeeded"}
```

## JSONL 可以做什么

JSONL 适合保存 Agent transcript，因为：

- append 简单。
- 人和脚本都容易读取。
- 每行一个事件或消息，适合流式写入。
- 方便脱敏、切片和导入评测集。

Qwen Code 的 background subagent transcript 就采用 JSONL，并配套 meta sidecar。它记录 ChatRecord 形态的 assistant、tool_result、external_message、system bootstrap 等内容，并通过 `uuid` 和 `parentUuid` 维护链路。

相关本地源码：

- `/Users/chigao/Documents/codebase/github/qwen-code/packages/core/src/agents/agent-transcript.ts`
- `/Users/chigao/Documents/codebase/github/qwen-code/packages/core/src/agents/background-agent-resume.ts`
- `/Users/chigao/Documents/codebase/github/qwen-code/packages/core/src/tools/agent/agent.ts`

## qwen-code JSONL 能否复现和回放

答案分三层：

| 能力 | 是否可以 | 说明 |
| --- | --- | --- |
| 恢复对话上下文 | 可以 | qwen-code 已能从 JSONL 恢复稳定消息链，过滤不稳定尾部 |
| 复现用户场景 | 部分可以 | 可以看到 prompt、工具调用、tool result、assistant 输出 |
| 确定性回放 | 不完整 | 还缺 workspace 快照、模型响应固定、工具 I/O、环境和权限决策 |

因此，Qwen Code JSONL 是很好的恢复基础，但不能单独承担完整事件溯源。

## 完整回放还需要什么

要把某个 case 复现到足够接近原现场，至少记录：

| 类别 | 必须记录 |
| --- | --- |
| 代码现场 | repo URL、commit SHA、branch、diff、worktree snapshot |
| Agent 配置 | agent type、system prompt、tool allowlist/denylist、max turns、approval mode |
| 模型配置 | provider、model、temperature、tool schema、system prompt hash |
| 模型输出 | 原始 streaming delta 或最终 message/tool call |
| 工具输入输出 | shell command、exit code、stdout/stderr 引用、文件读写摘要 |
| 权限决策 | request、policy、approval/deny、审批人、时间 |
| 沙箱环境 | image digest、env 白名单、资源限制、网络策略 |
| 外部依赖 | npm/pip registry、API 返回、MCP server 版本 |
| artifact | diff、测试报告、最终摘要、日志 |

如果缺少模型输出，只能“重新跑一次”，结果可能不同。如果缺少 workspace 快照，工具调用即使一样也可能得到不同结果。

## 推荐事件模型

内部 canonical event 不应直接等同于某个 Agent 的 JSONL。建议用统一事件表：

```sql
create table run_events (
  id bigserial primary key,
  run_id text not null,
  seq bigint not null,
  type text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  unique (run_id, seq)
);
```

事件类型起步：

| 类型 | 用途 |
| --- | --- |
| `run.created` | run 创建 |
| `run.started` | worker 接管 |
| `agent.message.delta` | 模型流式文本 |
| `agent.message.completed` | 完整 assistant 消息 |
| `tool.call.requested` | 工具调用开始 |
| `tool.call.output` | 工具增量输出 |
| `tool.call.completed` | 工具调用完成 |
| `permission.requested` | 权限请求 |
| `permission.resolved` | 权限决策 |
| `artifact.created` | 产物创建 |
| `checkpoint.created` | 检查点 |
| `run.heartbeat` | worker 心跳 |
| `run.completed` | 成功 |
| `run.failed` | 失败 |
| `run.cancelled` | 取消 |

## 与 OpenCode 的启发

OpenCode 的 `session-event.ts` 很适合作为事件类型设计参考。它把 session 中的 AgentSwitched、ModelSwitched、Prompted、Shell.Started/Ended、Step.Started/Ended/Failed、Tool.Called/Progress/Success/Failed、Compaction 等都建成强类型事件。

相关本地源码：

- `/Users/chigao/Documents/codebase/github/opencode/packages/opencode/src/v2/session-event.ts`
- `/Users/chigao/Documents/codebase/github/opencode/packages/opencode/src/v2/session.ts`

这说明生产系统需要的不是“日志字符串”，而是可消费、可索引、可转换的事件 schema。

## 在线事件与离线 JSONL 的关系

建议采用双层：

```text
Postgres run_events = canonical event store
JSONL export = agent transcript / debug artifact / eval fixture
```

在线服务读 Postgres：

- UI 展示。
- 状态查询。
- 审计。
- 权限流。
- 重试和恢复。

离线任务读 JSONL：

- case 复盘。
- prompt 调优。
- regression eval。
- bug report。
- 模型回放 fixture。

## 回放模式

| 模式 | 目标 | 要求 |
| --- | --- | --- |
| Transcript replay | 重建对话和工具历史 | JSONL 足够起步 |
| State replay | 重建 run 状态 | canonical events |
| UI replay | 重放用户看到的流式过程 | delta events + timestamps |
| Tool replay | 不重新执行工具，使用录制结果 | tool input/output fixtures |
| Deterministic replay | 尽量复现原执行 | workspace snapshot + model/tool fixtures |
| Resume | 从中断点继续执行 | stable message chain + workspace + config |

## MVP 建议

1. 保留 Qwen Code 原生 JSONL。
2. 由 adapter 把 JSONL 和 runtime signal 转成内部 run_events。
3. 大字段保存到 artifact，事件里只放引用。
4. 每个 run 结束时导出：
   - `transcript.jsonl`
   - `events.jsonl`
   - `meta.json`
   - `diff.patch`
   - `final.md`
5. 回放工具先支持 transcript replay 和 state replay，再做 tool/model mock replay。

## 最小 `meta.json`

```json
{
  "run_id": "run_1",
  "agent": "qwen-code",
  "repo": {
    "url": "git@example.com:org/repo.git",
    "commit": "abc123"
  },
  "sandbox": {
    "image": "qwen-code-runner@sha256:...",
    "memory": "768m",
    "cpus": "0.75",
    "network": "egress-proxy"
  },
  "model": {
    "provider": "qwen",
    "model": "qwen3-coder",
    "temperature": 0
  },
  "artifacts": {
    "transcript": "transcript.jsonl",
    "events": "events.jsonl",
    "diff": "diff.patch"
  }
}
```

## 结论

事件溯源是云端 Agent 的基础设施能力。JSONL 是非常实用的承载格式，但真正可靠的长期运行系统，还需要把 run、tool、permission、artifact、checkpoint 和 sandbox 都纳入统一事件模型。
