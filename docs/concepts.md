# 核心概念

AgentFlow 的用户视角是 Task-first：用户提交任务，系统自动规划、调度、执行、审计并交付产物。底层仍有 Run、Worker、Executor 等实现对象，但它们属于 Admin 和排障语境。

## Task

Task 是用户看到的主要对象。

一个 Task 包含：

- 用户目标和上下文。
- Agent 计划和 Workflow/DAG。
- Agent Chat 和 WebShell 事件投影。
- 子 Agent 的角色、目标、产出物和评估结果。
- 产物、审计包、回放和重试记录。

常见状态：

| 状态 | 含义 |
| --- | --- |
| `queued` | 已创建，等待编排或执行资源 |
| `running` | Agent 正在执行 |
| `blocked` | 等待权限、资源或人工处理 |
| `completed` | 已完成并生成结果 |
| `failed` | 执行失败，可查看原因并重试 |
| `cancelled` | 已取消 |

## Agent Adapter

Adapter 是统一接入不同 Agent CLI 的协议层。

| Adapter | 典型用途 |
| --- | --- |
| `fake` | smoke test、部署验收、端到端链路验证 |
| `qwen` | qwen-code 真实执行 |
| `codex` | Codex CLI 真实执行 |
| `claude` | Claude Code 真实执行 |
| `opencode` | OpenCode 真实执行 |
| `auto` | 由策略选择可用 adapter |

真实 CLI adapter 需要在执行单元上安装对应命令，并通过环境变量启用真实执行模式。未启用时，系统可以用协议模拟路径验证控制面和 UI。

## Workflow 和 DAG

简单任务可以由一个 Agent 完成。复杂任务会生成 Workflow/DAG：

- orchestrator 负责拆解目标。
- 子 Agent 有明确角色、上下文、目标和产出物。
- 子任务可以并行、串行或 fan-out/fan-in。
- 每个子任务都需要事件、artifact 和评估结果。

生产 profile 可以接入 Temporal；轻量部署可以使用内置 durable workflow。

## Execution Unit

Execution Unit 是可被调度的执行资源。它可以代表：

- 本机隔离 workspace。
- Docker 容器执行池。
- ECS/云主机。
- NAS 或工作站。
- 远程 worker 进程。

Admin 会根据 unit 的 labels、resources、adapters、features 和健康状态选择执行位置。

## Worker 和 Executor

Worker 是主动向控制面心跳、认领任务并上传事件的后台进程。

Executor 是 Worker 为某个 Task/Run 启动的真实执行实例，例如 qwen serve、per-run CLI process 或容器。

简单理解：

| 对象 | 回答的问题 |
| --- | --- |
| Execution Unit | 哪台机器或哪个资源池可以接任务 |
| Worker | 谁在主动领任务并汇报心跳 |
| Executor | 某个任务实际由哪个进程/容器执行 |

## Channel

Channel 是任务入口和通知出口。当前设计预留并支持：

- Web 和移动端 Web。
- 钉钉机器人。
- 飞书机器人。
- 企业微信机器人。

Channel 消息不会绕过任务、权限和审计系统。入站消息会创建 Task，出站消息会记录发送状态，审批动作会写入审计事件。

## Artifact 和 Audit

Artifact 是任务产物，例如报告、日志、诊断文件、事件 JSONL、代码 diff、评估结果。

Audit 是可复盘证据链：

- 用户输入。
- Agent 输出。
- 工具调用。
- 权限审批。
- 执行单元和 executor 状态。
- 失败原因、重试、回放和评估结果。

普通用户优先看 Result 和 Artifacts；管理员和 auditor 再看 Canonical Events、Replay、Audit Bundle。

## Tenant、User 和 RBAC

Tenant 是租户配置边界。User 属于租户。RBAC 决定用户能访问哪些任务、配置和审计材料。

常见角色：

| 角色 | 适合对象 |
| --- | --- |
| `member` | 普通任务发起者 |
| `operator` | 处理任务失败、执行单元和权限请求 |
| `auditor` | 查看审计材料和任务历史 |
| `owner` | 管理租户、用户、RBAC、Channel、执行单元和部署配置 |

当前自托管默认以单租户 owner 起步，团队和企业使用时应在 Admin 中显式配置用户、角色和策略。
