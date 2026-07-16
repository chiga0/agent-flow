# 快速开始

这篇文档帮助你从“刚部署好”走到“完成第一个可审计任务”。如果你是普通用户，只需要看 Client 部分；如果你负责部署和运维，继续完成 Admin 和 smoke 验证。

## 1. 访问入口

Client 面向任务发起者：

```text
https://<你的域名>/cloud-agents/#/
```

Admin 面向 owner、operator、auditor：

```text
https://<你的域名>/cloud-agents/#/admin
```

登录使用部署时配置的本地邮箱账户：

| 字段 | 来源 |
| --- | --- |
| 邮箱 | `RUN_MANAGER_BOOTSTRAP_EMAIL` 或 GitHub Secret `RUNTIME_AUTH_EMAIL` |
| 密码 | `RUN_MANAGER_BOOTSTRAP_PASSWORD` 或 GitHub Secret `RUNTIME_AUTH_PASSWORD` |

如果兼容部署没有配置 `RUNTIME_AUTH_PASSWORD`，部署 workflow 会兼容使用 `RUNTIME_BASIC_AUTH_PASSWORD` 作为登录密码。不要把密码写入仓库、文档或聊天记录。

## 2. 创建第一个任务

第一次验证请用 `fake` adapter，先确认平台链路健康：

1. 打开 Client。
2. 在任务输入框写入：`请回复 OK，并说明当前任务链路可用。`
3. Adapter 选择 `fake`。
4. 提交任务。
5. 进入 Task Detail，确认能看到 `Agent Chat`、状态、Workflow、Canonical Events、Artifacts。
6. 下载或预览产物，确认任务完成。

fake 任务通过后，再尝试 `qwen` 或其他真实 adapter。真实 adapter 依赖 CLI 命令、模型配置、机器资源、workspace 隔离和权限策略，排障复杂度明显更高。

## 3. 真实 Agent 验证顺序

建议按这个顺序逐步打开能力：

| 顺序 | 验证项 | 成功标准 |
| --- | --- | --- |
| 1 | fake task | Task completed，事件和产物完整 |
| 2 | Admin overview | 队列、Workflow、HA、Channel 状态可读 |
| 3 | Execution Unit | 至少一个 active unit 或 worker 心跳正常 |
| 4 | qwen task | Agent Chat 有真实输出，artifact 中有日志或报告 |
| 5 | IM Channel | 平台消息能创建 task，出站消息可审计 |
| 6 | Retry/Replay | 失败任务可以重试，历史事件可以回放 |

## 4. 普通用户应该看什么

普通用户只需要理解四个区域：

| 区域 | 作用 |
| --- | --- |
| New Task | 描述目标、选择简单/复杂任务、选择 adapter |
| Recent Tasks | 找到自己最近提交的任务 |
| Agent Chat | 实时看 Agent 输出、工具调用和需要你处理的动作 |
| Artifacts / Result | 查看最终结果、报告、日志和审计材料 |

不要从 Admin 的 Run、Worker、Executor 开始学习。那些是运维和审计视角。

## 5. 管理员上线检查

管理员部署后至少检查：

1. [Admin 管理指南](admin-guide.md) 中的 Overview、Execution Units、Channels、Tenants、HA。
2. [执行单元注册与调度](execution-units.md) 中的 unit/worker 注册。
3. [IM 机器人接入](channel-integrations.md) 中的签名校验和回调代理。
4. [部署指南](deployment-runbook.md) 中的 smoke、备份、监控和资源建议。

2C2G 机器建议只跑低并发控制面或单 worker。真实 qwen、Playwright、前端构建、Docker build 和多任务并发不要挤在同一台 2C2G 上。
