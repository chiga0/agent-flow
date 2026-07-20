# Admin 管理指南

Admin 面向 owner、operator、auditor 和平台运维者。它负责让 aflow 可控、可审计、可恢复，而不是替代 Client 成为普通用户入口。

入口：

```text
https://<你的域名>/cloud-agents/#/admin
```

## 1. Overview

Overview 用来判断系统整体是否健康：

- 任务数量、运行中任务、失败任务。
- 队列和 Workflow 状态。
- 执行单元健康度。
- Channel 配置和消息状态。
- HA profile、数据库、队列、worker 和备份配置摘要。

如果用户反馈“任务没动”，管理员先看 Overview，再进入 Execution Units、Workflow 或具体 Task 的审计信息。

## 2. Execution Units

Execution Units 管理可调度资源。

你可以：

- 从 `V2_EXECUTION_UNITS_JSON` 发现本机、NAS、Docker、ECS 等资源。
- 在 Admin 中手动注册 unit。
- 查看 unit 的 kind、labels、resources、adapters、features、status。
- 标记资源是否可接真实 adapter。
- 结合 worker 心跳判断任务为什么排队。

低配 2C2G 机器建议：

- `capacity=1`。
- 只跑轻量任务或作为公网边缘。
- qwen/codex/claude/opencode 真实任务先从单并发开始。

## 3. Channels

Channels 管理钉钉、飞书、企业微信等机器人。

Admin 需要配置：

| 配置 | 用途 |
| --- | --- |
| webhook URL | aflow 主动向群里发送消息 |
| callback token / secret | 入站消息签名校验 |
| tenant mapping | 群消息归属哪个租户 |
| user mapping | 群用户映射到哪个 aflow 用户 |
| policy | 哪些群可以创建任务、审批、接收结果 |

生产环境不要把无保护的 `/v2/channels/{platform}/webhook` 直接暴露给公网。推荐在边缘代理完成平台签名校验，再转发到 aflow。

## 4. Tenants、Users 和 RBAC

Tenant 是组织配置边界。owner 可以在 Admin 中：

- 创建和编辑租户。
- 管理租户用户。
- 设置角色和 RBAC policy。
- 配置租户可用 adapter、执行单元和 Channel。
- 禁用用户或重置密码。
- 当前用户可在 Access 页面自助修改密码；新密码至少 12 位，修改后 token version 递增并撤销全部已有会话。
- 浏览器写请求使用 HttpOnly session cookie + CSRF token；API Token/Worker Bearer 调用不依赖浏览器 CSRF。

角色建议：

| 角色 | 权限建议 |
| --- | --- |
| `member` | 创建和查看自己的 Task |
| `operator` | 查看任务和执行状态，处理失败、重试和权限 |
| `auditor` | 只读查看事件、产物和审计材料 |
| `owner` | 管理用户、租户、RBAC、Channel、执行单元和部署策略 |

## 5. Workflow Engine

Workflow Engine 决定复杂任务如何持久化、重试和恢复。

| Profile | 适用场景 |
| --- | --- |
| 内置 durable engine | 单机、自托管、低并发 |
| Redis queue | 多 worker、需要更强队列能力 |
| Temporal profile | 长任务、人工审批、失败恢复、水平扩展 |

Admin 中的 Workflow 页面用于查看当前 profile、task queue、worker 副本数、失败重试和最近状态。

## 6. HA 和备份

生产或团队使用建议启用：

- Postgres 持久化。
- Redis 队列。
- Temporal profile。
- 多 worker 副本。
- artifact 共享卷、NAS 或对象存储。
- 定期备份和恢复演练。

2C2G VPS 不建议作为完整 HA 节点。更合理的定位是公网入口或单 worker；控制面和数据库放在 NAS、工作站或更大云主机。

压测前后都要检查 `/health`，并用 `scripts/validate_ha_load.py` 记录吞吐和 p95。当前推荐的生产拓扑是单控制面 + 多远程 Worker；在 V2 领域数据完全迁移到共享 Postgres 之前，不要把 Runtime 控制面直接扩成多副本。

## 7. 审计闭环

管理员和 auditor 需要关注：

- 每个 Task 的目标、输入和 source。
- 每个子 Agent 的 role、context、artifact contract。
- CLI 原始日志和标准化事件。
- 权限请求、审批人、审批理由。
- retry/replay 记录。
- evaluation 结果。
- artifact manifest 和 audit bundle。

审计材料必须能回答：谁发起了任务、Agent 做了什么、为什么这样做、产物在哪里、失败时如何恢复。

## 8. 上线检查清单

上线前至少完成：

- fake task 成功。
- 一个真实 qwen/codex/claude/opencode task 成功。
- 至少一个 active execution unit。
- Channel 出站和入站 smoke 成功。
- owner 可以创建 member/operator/auditor。
- 失败任务可以 retry，历史任务可以 replay。
- 备份可以生成，恢复路径有文档。
- CI 和部署 workflow 全绿；如配置了外部监控，其 health/深度检查正常。
