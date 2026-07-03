# 核心概念

这篇只解释用户需要先理解的概念。更底层的协议、沙箱、事件溯源和多 Agent 设计可以之后再读架构文档。

## Run

Run 是一次 Agent 执行。

你在 `Runs` 页面提交一个 prompt，就会创建一个 run。run 有自己的状态、事件、artifact、executor 信息和审计包。

常见状态：

| 状态 | 含义 |
| --- | --- |
| `queued` | 已入队，等待 worker 或 executor |
| `running` | 正在执行 |
| `waiting_approval` | 等待人工审批权限 |
| `completed` | 已完成 |
| `failed` | 执行失败 |
| `cancelled` | 已取消 |

## Adapter

Adapter 是接入真实 Agent 的适配层。

当前常用 adapter：

| Adapter | 用途 |
| --- | --- |
| `fake` | 平台链路 smoke test，成本低、稳定 |
| `qwen` | 调用 qwen-code 执行真实任务 |

如果你只是验证部署是否成功，先用 `fake`。如果 fake 正常但 qwen 失败，通常说明平台主链路可用，问题在 qwen 设置、机器资源、权限审批或 executor。

## Mission

Mission 是比 run 更高一层的复杂任务。

一个 mission 会把目标拆成多个 task，每个 task 可以使用不同 profile，例如 planner、coder、tester、reviewer。底层仍然会创建一个或多个 run。

适合 mission 的任务：

- 需要先分析、再实现、再测试、再 review。
- 需要多个子任务并行。
- 需要 reviewer 或 release gate 给出结论。

## Profile

Profile 是执行模板，不是一个长期在线的 Agent。

它描述某类任务应该用什么 prompt、工具策略、审批策略、资源限制和 artifact 输出。内置 profile 包括 planner、coder、tester、reviewer、release-gate、doc-writer。

## Worker 和 Unit

Worker 是会主动向控制面报到并认领任务的执行进程。Unit 是管理台里看到的执行单元视图。

你可以把控制面部署在一台更稳定的机器上，再把 2C2G VPS 注册成 capacity=1 的 worker。这样 qwen 或构建任务卡住时，不容易拖垮 Web 管理台。

关键字段：

| 字段 | 含义 |
| --- | --- |
| `capacity` | 这个 worker 同时能跑多少个任务 |
| `heartbeat` | worker 最近一次报到时间 |
| `labels` | region、tier、用途等标签 |
| `metrics` | CPU、内存、磁盘、swap、load 等资源水位 |

注册 worker 时生成的一次性令牌是一个最小权限 API token，通常只包含 `workers:*`。它只在创建时显示一次；如果部署命令丢失或令牌泄露，重新生成并撤销旧 token。

## Executor

Executor 是 qwen adapter 背后的具体运行策略。

常见策略：

| 策略 | 含义 |
| --- | --- |
| `shared` | 共用一个 qwen serve，资源开销低 |
| `per_run_process` | 每个 run 启动独立 qwen 进程，隔离更好 |
| `container` | 每个 run 用容器执行，隔离 foundation 已有但仍需更多实机验收 |

当 qwen run 失败时，`Executors` 页面和 run artifact 里的 stdout/stderr 是关键线索。

Executor Registry 是控制面记录 executor lease 的注册表，包含 run_id、executor_id、strategy、pid、port、workspace、status 和 last_error。它不是 worker 注册表；worker 注册表回答“有哪些机器能接任务”，executor registry 回答“这些机器为哪些 run 拉起了哪些执行实例”。

## Artifact 和 Audit Bundle

Artifact 是任务执行过程中产生的材料，例如事件 JSONL、diagnostics、executor 日志、最终报告。

小型文本产物可以在管理台直接预览。固定的“审计下载”区用于下载事件、诊断和完整审计包；具体文件仍在 Artifact 区按名称展示。

Audit Bundle 是把关键材料打包后的审计包，适合用来复盘：

- 当时输入了什么。
- Agent 输出了什么。
- 调用了哪些工具。
- 哪些权限被批准或拒绝。
- 失败时 executor 和 worker 的状态是什么。

## Permission

Permission 是 Agent 执行高风险操作前发起的人工审批请求。

例如 shell 命令、文件写入、网络访问、git 操作等都可能触发审批。你需要在 Run Detail 的 Agent Chat 或 Permission 区域批准/拒绝，并填写 reason。

如果 run 长时间没有更新，先检查它是不是在等待权限。

## Account 和 Token

浏览器登录使用本地邮箱账户。部署时配置 owner email/password，系统会 bootstrap 一个 owner 用户。

API token 用于自动化和 worker 接入。token 只在创建时显示一次，服务端只保存 hash。worker 建议使用带 `workers:*` scope 的 token，不要把 master token 暴露给 worker。
