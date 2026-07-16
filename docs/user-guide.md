# Client 使用指南

Client 是普通用户的主入口，目标是让用户不用理解 worker、executor、lease、run schema，也能快速发起任务、持续观察进度、处理必要权限并拿到结果。

## 1. 进入工作台

打开：

```text
https://<你的域名>/cloud-agents/#/
```

登录后默认进入任务工作台。普通 `member` 用户只看到自己的任务；`owner` 可以看到全部任务，并可以从页面跳转到 Admin 做排障。

## 2. 发起任务

在 New Task 区域填写：

| 字段 | 建议 |
| --- | --- |
| Goal | 用自然语言描述你希望 Agent 完成什么 |
| Mode | 简单任务用 single，复杂任务用 workflow/orchestrated |
| Adapter | 第一次验证用 `fake`，真实任务再选 `qwen`、`codex`、`claude` 或 `opencode` |
| Workspace | 有固定代码仓库或数据目录时再指定 |

页面提供了任务模板。第一次使用可以直接点模板，再按你的真实目标修改。

## 3. 查看 Task Detail

Task Detail 是用户完成任务的核心页面。

| 区域 | 用途 |
| --- | --- |
| Status | 当前状态、耗时、成本和完成度 |
| Agent Chat | 默认聊天区，展示 WebShell/DaemonEvent、Agent 输出、工具摘要和错误 |
| Follow-up input | 任务仍可交互时，继续补充要求或上下文 |
| Workflow / DAG | 查看 orchestrator 如何拆分子 Agent 和依赖 |
| Artifacts | 预览或下载报告、日志、诊断和评估材料 |
| Evaluations | 查看子任务和最终产物是否达标 |
| Replay / Retry | 复盘历史输入，或按策略重试失败任务 |
| Canonical Events | 面向审计和排障的底层事件流 |

用户日常优先看 Agent Chat、Workflow 和 Artifacts。Canonical Events 是最后的排障证据，不是首要阅读区域。

## 4. 什么时候追加消息

适合追加消息的情况：

- Agent 仍在运行，你要补充约束。
- Agent 请求你确认范围、权限或偏好。
- 你希望它调整输出格式。
- 你要把简单任务继续推进一步。

不适合追加消息的情况：

- 任务已经 `completed`、`failed` 或 `cancelled`。
- 你要彻底改变目标。
- 你需要换 adapter、换 workspace 或换执行策略。

这些情况建议创建新任务，或让管理员从 Admin 端执行 retry/replay。

## 5. 如何判断任务是否健康

| 现象 | 先看哪里 | 下一步 |
| --- | --- | --- |
| 一直 queued | Status / Workflow | 让管理员检查 Execution Units 和 worker capacity |
| 一直 running | Agent Chat | 看是否仍有输出；没有输出再看 Events |
| 等待用户 | Agent Chat / Status | 处理权限或补充信息 |
| failed | Result / Events / Artifacts | 查看失败摘要、executor stderr、diagnostics，再 retry |
| 没有产物 | Artifacts | 看 Workflow 是否完成，或查看评估失败原因 |

## 6. 移动端使用

移动端 Web 的设计目标是完成四件事：

- 快速提交任务。
- 查看当前状态和 Agent Chat。
- 处理权限或确认。
- 下载或打开最终结果。

复杂的 Admin 配置、长日志、执行单元注册更适合桌面端处理。

## 7. 用户不需要理解的实现细节

以下对象对普通用户默认隐藏：

- Run lease。
- Worker heartbeat。
- Executor PID 和端口。
- 事件 schema。
- adapter stdout/stderr。
- HA profile 和队列实现。

当任务失败或需要审计时，owner/operator/auditor 可以在 Admin 中继续追踪这些信息。
