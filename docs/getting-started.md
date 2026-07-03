# 认识 AgentFlow

AgentFlow 的目标是把“在本地 CLI 里跑一次 Agent”变成“可以长期运行、可以审计、可以恢复、可以交给 worker 执行的任务系统”。

你可以把它理解成三个东西组合在一起：

- 一个 Web 管理台：创建任务、看进度、处理权限、下载结果。
- 一个 Run Manager：保存任务状态、事件流、artifact、审计包和 worker 心跳。
- 一组执行单元：本机或远程 worker，实际运行 fake/qwen 等 Agent adapter。

## 它解决什么问题

普通 Agent CLI 很适合本地交互，但长期运行时会遇到这些问题：

- 浏览器或终端断开后，不知道任务是否还在继续。
- 模型输出、工具调用、权限审批、失败原因分散在日志里。
- qwen 之类真实执行器容易消耗 CPU/内存，小 VPS 上更明显。
- 多个任务并行时缺少队列、容量、worker、审计和恢复机制。

AgentFlow 把这些能力放到一个运行时里，让任务可以被创建、排队、认领、执行、审批、取消、重试、归档和审计。

## 当前能做什么

当前 beta 版适合下面这些场景：

- 用 `fake` adapter 验证部署、登录、事件流、artifact 和监控链路。
- 用 `qwen` adapter 跑真实轻量任务，并查看实时输出和 executor 日志。
- 创建 mission，把一个目标拆成多个 profile task 执行。
- 注册远程 worker，让控制面和执行面分离。
- 在 Run Detail 中处理权限请求，并下载 audit bundle。
- 通过 GitHub Actions 把最新 main 自动部署到一台 VPS。

当前不适合直接当成开放式多租户 SaaS 使用。邮箱验证、找回密码、多组织、精细计费、外部通知渠道和更强的隔离边界仍需要继续建设。

## 第一次上手

建议先用一条 fake run 建立直觉：

1. 打开管理台，例如 `https://your-domain/cloud-agents/`。
2. 使用部署时配置的邮箱和密码登录。
3. 进入 `Runs`，adapter 选 `fake`。
4. 输入一个短 prompt，例如 `hello runtime`。
5. 创建后进入 Run Detail。
6. 查看 Agent Chat、Event Stream、Artifacts 和 Audit Bundle。

fake run 成功后，再尝试 qwen run。qwen 会依赖机器资源、qwen CLI、settings、权限审批和 executor 策略，所以更适合放在第二步验证。

## 学习路径

按这个顺序继续：

1. [核心概念](concepts.md)：先读懂系统里的名词。
2. [使用管理台](user-guide.md)：学习每个页面如何使用。
3. [自我部署](self-deploy.md)：把系统部署到自己的机器。
4. [排障手册](troubleshooting.md)：出现问题时按症状定位。
5. [产品可用性审计](implementation/product-usability-audit.md)：了解当前仍缺什么。
