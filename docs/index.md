# AgentFlow

AgentFlow 是一个可自托管的 Agent 运行时：你可以把一个 AI 编程任务放到云端或自己的机器上长期运行，随时查看进度、处理权限请求、下载审计材料，并把执行能力扩展到多台 worker。

当前版本更接近“单租户 beta 运行平台”，不是已经完成的 SaaS 产品。它已经能跑 fake/qwen 任务、mission、worker、executor、artifact、audit、权限审批和基础账户认证；多租户、邮箱验证、支付、企业级权限边界仍在演进。

## 建议阅读顺序

如果你是第一次接触这个项目，建议按下面顺序读：

1. [认识 AgentFlow](getting-started.md)：先了解产品解决什么问题，以及当前能做什么。
2. [核心概念](concepts.md)：弄清 run、mission、worker、executor、artifact、permission 这些词。
3. [使用管理台](user-guide.md)：按页面学习如何创建任务、看进度、处理权限和下载审计包。
4. [自我部署](self-deploy.md)：把它部署到自己的 VPS、本地电脑或 NAS。
5. [排障手册](troubleshooting.md)：遇到登录失败、一直 running、qwen 失败、CI 部署失败时从这里查。

读完这五篇，你已经可以作为使用者和自部署者上手。后面的“运维与审计”“架构设计”“研究资料”面向二次开发和方案评审。

## 当前产品状态

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Web 管理台 | 可用 | 支持 Run、Mission、Units、Executors、Access、Operations 等页面 |
| 本地邮箱账户登录 | 可用 | 使用部署时配置的 owner email/password；暂未接 SMTP 邮件验证 |
| fake run | 稳定 | 适合 smoke test 和链路验证 |
| qwen run | 可用 | 支持 shared、per-run process、container foundation，真实任务仍需关注资源 |
| mission 编排 | 可用 | 支持轻量 DAG、profile、review gate foundation |
| remote worker | foundation 可用 | 支持 heartbeat、claim、event 回传、artifact 上传 |
| 审计材料 | 可用 | run/mission event、diagnostics、executor 日志、audit bundle |
| 多租户 SaaS | 未完成 | 当前按单租户/个人自托管设计 |

## 最小本地预览

文档站：

```bash
python -m pip install -r requirements.txt
mkdocs serve
```

Runtime：

```bash
python3 -m runtime.cloud_agents_runtime --host 127.0.0.1 --port 8765
```

生产部署请直接看：[自我部署](self-deploy.md)。
