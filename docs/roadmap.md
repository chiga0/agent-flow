# Roadmap

这份 Roadmap 只描述当前 aflow 产品后续要补齐的能力，不再保留历史版本或早期阶段划分。

## 已完成的基础能力

| 能力 | 状态 |
| --- | --- |
| Client/Admin 分离 | 已落地，普通用户默认进入 Client，后台能力进入 Admin |
| Task-first 模型 | 已落地，用户通过 Task 而不是 Run 发起任务 |
| Agent Chat | 已落地，Task Detail 中 WebShell/DaemonEvent 是核心区域 |
| 多 Agent DAG 投影 | 已落地基础视图，复杂任务可展示 Workflow |
| 统一 adapter | 已支持 fake/qwen/codex/claude/opencode 接入模型 |
| 执行单元注册 | 已支持环境发现、Admin 注册、worker 注册 |
| Channel 基础链路 | 已支持钉钉、飞书、企微配置、入站、出站和审计 |
| Admin 多租户基础 | 已支持 tenants、users、RBAC 基础配置 |
| HA profile | 已有 Postgres/Redis/Temporal/worker 部署 profile |
| CI/CD | Runtime CI、Deploy Runtime、Deploy MkDocs 已接入；定时 Runtime Monitor 已关闭 |
| 执行模式可见性 | Task 列表、详情和事件区分 real-cli、protocol-simulated、fake |
| WebShell 实时流 | V2 Agent Chat 使用带断线续传的 SSE，轮询仅作为降级 |
| 失败摘要与结果页 | failed task 提供原因、影响、下一步；Artifact 支持预览、下载和审计包 |
| Project membership | 项目成员支持 owner/editor/viewer/member，Task 与 Artifact 统一鉴权 |
| Temporal workflow | HA profile 包含 Temporal SDK dispatcher、独立 worker 和 activity 回调 |
| 真实 CLI 深度 smoke | 保留手工脚本，按需验证 Agent 的 real-cli 模式和产物，不再由定时 CI 触发 |

## P0：上线可用性

| 项 | 目标 |
| --- | --- |
| Channel 未配置态 | 未配置的平台在 Client/Admin 中明确禁用或提示配置入口 |
| 失败摘要 | 已完成；failed task 自动生成原因、影响和下一步建议 |
| 真实 CLI 可见性 | 已完成；页面明确区分真实 CLI、协议模拟、fake adapter |
| WebShell 实时性 | 已完成；Agent Chat 使用 SSE，轮询作为降级 |
| Artifact 结果页 | 已完成；提供最终摘要、下载、预览和审计包入口 |

## P1：团队使用

| 项 | 目标 |
| --- | --- |
| Admin 子页面拆分 | Tenants、Users、RBAC、Channels、Execution Units、HA 分区更清楚 |
| Project membership | 已完成基础闭环；普通用户可在项目范围内共享 Task |
| Artifact 授权 | 已完成 V2 Task/Artifact/Audit 统一项目访问判断 |
| 用户自助安全 | 已完成改密码、token_version、全 session 失效、浏览器 CSRF 与强密码门禁 |
| 移动端审批 | 手机端完成权限处理和结果查看 |

## P2：生产级执行

| 项 | 目标 |
| --- | --- |
| Temporal 深度接入 | 已接入 V2 task dispatcher/worker/activity；审批信号仍需继续深化 |
| V2 Remote Worker | 已完成 Agent Task lease、隔离 workspace、实时事件/artifact、取消、审批投递、重试与失联回收 |
| HA/压力验证 | V2 领域已支持 PostgreSQL 共享状态、跨控制面租约竞争 smoke、HA Compose 校验和并发吞吐验证；完整 HTTP 多副本仍需迁移 V1 RunStore/Auth 状态 |
| 执行单元调度策略 | 基于资源、标签、租户、adapter、成本选择 unit |
| Docker/ECS/NAS 生产化 | workspace 隔离、secret 注入、资源限制、日志回收 |
| Worker 水平扩展 | 多 worker 副本、健康检查、drain/resume、迁移 |
| 备份恢复演练 | Postgres、artifact、配置、audit 可恢复 |

## P3：企业治理

| 项 | 目标 |
| --- | --- |
| 企业身份 | SSO/OIDC、SCIM 或外部 IAM |
| 租户隔离 | 数据、artifact、secrets、执行单元策略隔离 |
| 审计导出 | 按 task/user/project/channel 导出完整审计 |
| 成本和限额 | 租户级预算、adapter 配额、并发限制 |
| 灰度发布 | Runtime 和 worker 支持版本策略和回滚 |

## 每阶段门禁

任何阶段完成都必须通过：

- 后端单元和集成测试。
- Web 单测和 E2E。
- 文档更新。
- 安全和权限审计。
- 产品流程审计。
- Runtime CI 和部署 smoke。
