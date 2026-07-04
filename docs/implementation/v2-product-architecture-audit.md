# AgentFlow V2 多轮审计记录

> 日期：2026-07-04  
> 对象：[AgentFlow V2 产品与架构整体方案](v2-product-architecture.md)  
> 目标：通过多轮、多角色、多失败模式审计，确认 V2 方案方向、边界和实施路线没有明显结构性问题；把剩余风险转成后续实现门禁。  
> 结论：方案方向可行，建议进入 `design_ready_for_review`；但 V2-P2 的正式认证、用户隔离和权限审计是面向真实用户开放前的硬门槛。

## 审计方法

本轮不是只检查文案，而是按以下维度逐项审计：

1. 产品目标是否真正面向最终用户。
2. 用户端简化是否削弱后台治理。
3. Task / Mission / Run 分层是否稳定。
4. 多用户、租户、权限、审计是否闭环。
5. 云端长期执行、排队、隔离、恢复是否保留。
6. IM / App / 移动端入口是否会绕过安全边界。
7. 竞品经验是否被吸收，而不是闭门设计。
8. 实施路线是否可拆、可验收、不会一次性失控。

严重级别：

| 级别 | 含义 |
| --- | --- |
| P0 | 阻断项；不修不能进入实现或不能对用户开放 |
| P1 | 高风险；必须进入近期 Roadmap |
| P2 | 中风险；可随阶段推进 |
| P3 | 体验或长期优化 |

## 总体审计结论

| 维度 | 结论 | 说明 |
| --- | --- | --- |
| 产品方向 | 通过 | 用户端 Workspace + 后台 Admin/Ops/Audit 是正确分层 |
| 架构分层 | 通过 | Task 产品层不推翻 Run/Mission/Worker/Executor |
| 安全治理 | 条件通过 | 方案正确，但 V2-P2 是上线硬门槛 |
| 数据隔离 | 条件通过 | 需要实现 user/project/tenant 绑定和查询过滤 |
| 实时体验 | 通过 | canonical event 与 UI projection 分离是正确方向 |
| 调度隔离 | 通过 | 保留 queue/lease/worker/executor，技术细节不暴露给用户 |
| 竞品参照 | 通过 | 吸收 DeerFlow/OpenHands/CrewAI/LangGraph/n8n 的共性设计 |
| 实施可行性 | 通过 | V2-P1 到 V2-P6 可渐进实现 |

总判断：

```text
Go for implementation after owner review.
No-Go for public multi-user exposure until V2-P2 is complete.
```

## 2026-07-04 P2a 实施后审计

### 实施内容

本轮开始进入 V2-P2，先完成用户侧 Workspace 的最小数据隔离：

- `/tasks` 创建时写入 `created_by`、`project_id`、`visibility` 元数据。
- `/tasks` 列表、详情、事件、结果、artifact、追加消息、取消都接收同一访问上下文。
- session 用户默认只能看到自己创建的 task。
- owner 可查看全部 task。
- API token 身份进入同一 `current_identity` 流程，为后续 project-scoped token 做准备。
- 新增 `member` 角色，用于普通用户的 Workspace 主流程；`member` 不持有直接 `/runs` 后台读取权限。
- 前端导航按角色隐藏后台入口，member 默认只看到 Workspace。
- 新增 V2 独立实施 Roadmap，明确每阶段必须有审计和 E2E 门禁。

## 2026-07-04 P2b 实施后审计

P2b 在 P2a 用户 task 隔离基础上补齐 owner 页面内用户管理闭环：

- Access -> Users 创建用户默认角色从 `operator` 调整为 `member`。
- owner 可在用户行内改角色、禁用/启用、重置密码。
- 后端新增 `/auth/users/{email}/roles`、`/status`、`/password` 管理端点，统一受 `access:write` scope 保护。
- 后端统一校验角色，只允许 owner/operator/auditor/member。
- 禁用用户会撤销该用户现有 session；重置密码会更新密码并撤销该用户现有 session。
- 安全护栏：不允许当前用户禁用自己，不允许当前 owner 从自己身上移除 owner 角色。

### P2b Design Review

通过。

本轮继续沿用本地邮箱账户体系，没有引入外部 IdP 或 SMTP 邀请流。原因是当前目标是先让 owner 可以管理成员生命周期，并支撑小团队自部署；公开注册、邮件验证、忘记密码和 SSO 属于后续版本。

### P2b Security Review

条件通过。

已修复：

- 页面内创建普通用户不再默认授予 operator 后台能力，而是默认授予 `member`。
- 禁用用户和重置密码都会撤销该用户已存在 session。
- 当前 owner 不能在页面内误禁用自己。
- 当前 owner 不能移除自己的 owner 角色。

仍需 P2c 修复：

- 还没有 CSRF token，session 写操作仍依赖 SameSite cookie 与来源边界。
- 还没有用户自助改密码。
- 还没有 token_version/session_version 字段，因此“全量踢下线”的模型仍偏操作级，而不是版本化身份模型。
- API token 与用户 session 的生命周期仍未完全合并。

### P2b Product Review

通过。

管理员可以在同一 Access 页面完成“创建成员 -> 成员登录 Workspace -> 管理员调整/禁用”的闭环。普通用户仍不会看到后台入口。

### P2b Architecture Review

通过。

本轮只扩展 `auth_users` 现有事实源和 `auth_sessions` 撤销能力，没有新增用户表或迁移租户模型。Project membership 仍留给 P2d，避免在 P2b 中引入半成品项目成员语义。

### P2b Test Review

通过。

覆盖项：

- runtime integration：默认 member、改角色、重置密码旧密码失效、新密码可用、禁用后不能登录、不能禁用当前 owner。
- Web unit：Access 页面创建用户、改角色、重置密码、禁用，以及 API client 路径覆盖。
- Web E2E：管理员从 Access 页面创建成员并执行重置密码/禁用操作。

### Design Review

通过。

本轮没有新建 Task 表，而是先使用 Run/Mission metadata 建立产品层访问边界。这样可以最快保护用户端 Workspace，又不破坏现有 Run/Mission/Worker/Executor 事实源。

约束：

- Task projection 仍不是审计事实源。
- created_by/project_id/visibility 是产品访问元数据，后续可迁移为正式 task 表。
- 后台 Runs/Missions 仍是治理视图，P2a 只承诺 `/tasks` 用户入口隔离。

### Security Review

条件通过。

已修复：

- 普通 session 用户不能通过 `/tasks/{id}`、`/tasks/{id}/messages` 查看或操作他人任务。
- member 用户不能直接读取 `/runs` 后台列表。
- owner 仍可审计全部任务。
- API token identity 被写入 request context，不再只有 session 能进入访问上下文。

仍需后续 P2b-P2e 修复：

- Runs/Missions/Artifacts 的后台 API 仍按角色 scope 管控，不按 task owner 过滤。
- Project membership 还没有正式表结构。
- CSRF、改密码、token_version、session revoke-all 还没完成。
- Permission decision 的 `decided_by` 仍需强制以后端 session principal 为准。

### Product Review

通过。

本轮把“普通用户默认只在 Workspace 使用”推进了一步：

- 新增 `member` 角色。
- member 导航隐藏 Overview/Runs/Executors/Access/Operations 等后台页面。
- Workspace 创建任务和 Task Detail 仍保持用户任务语言。

产品风险：

- 当前管理员创建用户时仍需手动选择角色，缺少邀请/禁用/重置密码等完整账户生命周期。
- Task Detail 对 owner/operator/auditor 仍保留后台源链接，这是后台角色的必要排障入口；member 默认看不到后台导航，但后续还应对后台源链接做更细粒度角色判断。

### Architecture Review

通过。

本轮符合 V2 分层：

```text
Workspace Task projection -> Run/Mission metadata -> canonical event/audit source
```

没有把权限过滤散落到前端，而是在后端 manager 层集中判断，HTTP 层只负责传入当前身份。

### Test Review

已补充：

- Runtime integration test：owner 创建 Alice/Bob，Alice/Bob 分别创建任务，Alice 只能看到自己的任务，owner 可看全部。
- E2E：Workspace 创建 task 并进入 Task Detail。
- E2E：member 用户看不到后台导航。

本轮本地验收项：

- `python3 -m unittest discover -s runtime/tests -p 'test_runtime_server.py'`
- `python3 scripts/check_style.py`
- `npm run lint`
- `npm run test`
- `npm run build`
- `npm run test:e2e`

## 第一轮：产品目标审计

### 审计问题

最初需求是“始终在云端运行的个人/小企业/租户 Agent 系统”，而不是“runtime 管理台”。因此审计重点是 V2 是否真正把最终用户问题放在第一位。

### 发现

| 发现 | 级别 | 判断 |
| --- | --- | --- |
| 当前 V1 默认暴露 Run/Worker/Executor，普通用户认知负担高 | P1 | V2 已修正为 Workspace 默认入口 |
| 用户任务缺少统一产品对象，Run/Mission 都偏技术 | P0 | V2 引入 Task wrapper，解决 |
| 用户端结果页不能只是 artifact 列表 | P1 | V2 规定 Result Page 和完成定义 |
| 后台审计不应出现在用户首屏 | P2 | V2 分离 Admin/Ops/Audit |

### 结论

通过。

V2 的产品目标已经从“管理运行时”调整为“用户提交任务并获得结果”。这是必要且正确的重定位。

### 必须保持的原则

- 默认首页是 Workspace。
- 普通用户默认只看到 Task，不看到 Run/Worker/Executor。
- 结果页优先展示总结、产物、风险和下一步，而不是日志。

## 第二轮：目标用户审计

### 审计问题

V2 同时提到个人、小企业、大租户，容易范围过大。需要确认 MVP 是否能先服务清晰用户，而不是一次性做企业平台。

### 发现

| 用户 | 需求 | V2 是否覆盖 | 风险 |
| --- | --- | --- | --- |
| 个人用户 | 发起任务、看进展、拿结果 | 覆盖 | 需要降低设置成本 |
| 小企业 | 多人、项目、权限、审计 | 部分覆盖 | 需要 V2-P2 用户隔离 |
| 大租户 | 多租户、IAM、HA、合规 | 仅预留 | 不应放入 MVP |

### 修正建议

V2 MVP 只承诺：

- 个人。
- 小团队。
- 单实例自部署。
- 基础项目和角色。

企业能力作为 V2.2+：

- OIDC/SAML。
- 多控制面 HA。
- tenant worker pool。
- external secrets manager。
- object storage。

### 结论

通过，但 MVP 范围必须保持克制。

## 第三轮：竞品与外部方案审计

### 审计问题

方案是否闭门造车？是否吸收了外部优秀设计？

### 对照结果

| 方案 | 我们吸收的点 | 没有照搬的点 |
| --- | --- | --- |
| DeerFlow | Workspace、Skills、Artifact、Auth、用户端体验 | 不照搬 LangGraph 内部实现，不替换 runtime |
| OpenHands | Agent 产品需要 Cloud/Enterprise 和 RBAC 两层 | 不把 coding agent UI 当唯一场景 |
| LangGraph / LangSmith | durable execution、threads/runs、streaming | 不把全部业务状态交给框架 |
| CrewAI | agents/crews/flows 的任务角色表达 | 不让 crew 概念替代 runtime 审计边界 |
| n8n | workflow、credentials、execution history、integrations | 不把 AgentFlow 降级成通用自动化编排器 |
| AutoGen | multi-agent conversation/team/human-in-the-loop | 不把内部 subagent 当成用户端 task |

### 结论

通过。

V2 不是复制 DeerFlow，而是采用业界收敛的“用户任务工作台 + 后台治理 + runtime 底座”模式。

## 第四轮：架构分层审计

### 审计问题

新增 Task 产品层会不会和 Mission/Run 冲突？

### 分析

| 层 | 职责 | 是否保留 |
| --- | --- | --- |
| Task | 用户目标、状态、结果、通知、权限聚合 | 新增 |
| Mission | 多步骤 DAG 和 profile 编排 | 保留 |
| Run | 单次 Agent 执行事实边界 | 保留 |
| Worker | 执行单元和 capacity | 保留 |
| Executor | 真实 qwen/codex/claude/opencode 实例 | 保留 |
| RuntimeEvent | 审计事实源 | 保留 |

Task 不替代 Mission/Run，而是用户端 wrapper。

### 关键约束

- 一个 Task 可以映射到一个 Run。
- 一个 Task 可以映射到一个 Mission。
- 一个 Mission 可以包含多个 Run。
- Audit 仍以 Run/Mission canonical event 为事实源。
- Task event projection 不能成为审计事实源。

### 结论

通过。

此分层可实施，且不需要推翻现有 runtime。

## 第五轮：安全与权限审计

### 审计问题

用户端简单化是否会削弱权限？IM/App 入口是否绕过 Web 安全？

### 发现

| 风险 | 级别 | 修正 |
| --- | --- | --- |
| 用户端隐藏 event 后，危险操作可能被弱化表达 | P0 | Permission card 必须包含 action、reason、risk、scope、timeout |
| IM 按钮可能绕过 session/RBAC | P0 | Channel Gateway 必须映射真实身份或 scoped internal identity |
| approve_task 可能过宽 | P1 | 默认只提供 approve_once；approve_task 需 owner/project policy |
| secret 被注入 workspace 后泄漏 | P0 | secret 必须 run-scoped、最小权限、默认不写 artifact |
| 普通 member 看到后台审计 | P1 | Admin/Ops/Audit route 必须 role gate |

### 必须实现的门禁

V2 对真实用户开放前必须完成：

1. `/setup` 首次 owner。
2. HttpOnly session。
3. CSRF。
4. 登录限速。
5. token_version。
6. Task/Run/Artifact user/project/tenant 过滤。
7. Permission decision 全量审计。
8. Channel Gateway scoped identity。

### 结论

条件通过。

安全模型方向正确，但 V2-P2 是硬门槛。若只完成 V2-P1，不得开放给多用户或公网注册。

## 第六轮：数据隔离与多租户审计

### 审计问题

个人、小企业、租户共用一个系统时，数据是否会串？

### 数据隔离要求

| 对象 | 必须绑定 |
| --- | --- |
| Task | tenant_id、project_id、created_by |
| Mission | task_id、tenant_id、project_id |
| Run | task_id、mission_id、tenant_id、project_id、created_by |
| Artifact | run_id、task_id、tenant_id、project_id |
| Permission | task_id、run_id、requested_by_agent、decided_by |
| Worker | tenant scope 或 shared pool 标记 |
| ExecutorLease | worker_id、run_id、tenant/project metadata |

### 查询隔离规则

- member 只能看自己或项目授权 task。
- operator 可看项目内运行状态。
- auditor 可看授权范围审计。
- owner 可看租户内全部。
- guest 只能看被分享的 result，不看 audit。

### 结论

条件通过。

当前方案已预留 tenant/project，但实现时必须先做 project/user 级隔离，再谈大租户。

## 第七轮：调度、排队与长期运行审计

### 审计问题

V2 用户端隐藏后台细节后，是否仍能处理排队、卡住、重试、取消？

### 发现

| 场景 | 用户端表达 | 后台处理 |
| --- | --- | --- |
| 没有 worker | “暂无可用执行环境，任务已排队” | Admin 显示 worker stale/offline |
| worker 忙 | “前面还有 N 个任务” | Queue 显示 capacity/active |
| executor 卡死 | “Agent 无响应，正在恢复或等待处理” | Executor 详情显示 stdout/stderr |
| permission 未处理 | “等待你确认权限” | Permission timeout policy |
| long run | “Agent 正在执行第 X 步” | heartbeat + event projection |
| cancel | “正在取消任务” | run.cancel_requested / worker control |

### 结论

通过。

隐藏技术细节不等于删除诊断能力。用户端展示语义状态，后台端保留 runtime 事实。

## 第八轮：完成定义审计

### 审计问题

Agent 任务最大风险之一是“看起来结束了，但其实没有完成”。需要明确完成标准。

### 完成标准审计

V2 文档规定完成至少需要：

- 所有 required steps terminal。
- required artifacts 存在。
- reviewer 或 finalizer 给出结论。
- 未处理 permission 为 0。
- final summary 已生成。
- 失败/跳过项被明确记录。

补充要求：

| 要求 | 级别 |
| --- | --- |
| final summary 必须引用关键 artifact | P1 |
| failed/skipped step 必须进入 result risk section | P1 |
| 用户取消不能显示为 completed | P0 |
| 部分完成必须是 `partial` 或 `completed_with_warnings` | P1 |
| result page 必须可回链 audit | P2 |

### 结论

通过，但建议新增用户端状态：

- `completed`
- `completed_with_warnings`
- `partial`
- `failed`
- `cancelled`

## 第九轮：实时投影与审计事实源审计

### 审计问题

UI projection 会不会和 canonical events 不一致？

### 风险

| 风险 | 级别 | 处理 |
| --- | --- | --- |
| projection 丢事件，用户端看不到关键状态 | P1 | projection 可重建，task detail 可回放 |
| projection 被当成审计事实 | P0 | 文档明确 canonical events 是事实源 |
| projection 文案误导用户 | P2 | 事件映射表和测试覆盖 |
| Last-Event-ID 断线恢复不一致 | P1 | SSE resume 基于 canonical sequence |

### 结论

通过。

必须建立 `RuntimeEvent -> TaskTimelineEvent` 映射测试，确保 UI 友好但不篡改事实。

## 第十轮：实施范围审计

### 审计问题

V2 范围大，是否会一次性失控？

### 分阶段检查

| 阶段 | 是否可独立交付 | 说明 |
| --- | --- | --- |
| V2-P1 Workspace | 是 | 可先 wrapper 现有 run/mission |
| V2-P2 Auth/Isolation | 是 | 可独立提高安全性 |
| V2-P3 Default Planning | 是 | 基于现有 mission/profile |
| V2-P4 Files/Skills/Result | 是 | 可逐步接入 |
| V2-P5 IM/Mobile | 是 | 依赖 Task API |
| V2-P6 Admin 重构 | 是 | 可在 Workspace 后逐步迁移 |

### 结论

通过。

实施路线可拆，最大风险是试图同时做 Workspace、Auth、IM、Skills 和 Admin 重构。必须按阶段推进。

## 第十一轮：反向事故审计

从事故倒推方案是否能承受。

| 事故 | 影响 | 方案覆盖 | 剩余风险 |
| --- | --- | --- | --- |
| 用户批准危险命令后误删文件 | 数据损失 | permission audit + workspace isolation | 需要 snapshot/rollback |
| worker 掉线 | 任务卡住 | lease recovery + semantic status | long-running executor 恢复仍需实测 |
| projection 服务失败 | 用户看不到进度 | canonical events 可恢复 | 需要 projection rebuild |
| IM webhook 被伪造 | 越权审批 | scoped identity + signature | 需每个 channel adapter 实现验证 |
| artifact 泄漏给其他用户 | 数据泄漏 | user/project/tenant filter | 实现前不得开放多用户 |
| planner 生成过大计划 | 成本失控 | plan policy + budget | 需要默认步骤/成本上限 |
| public host 正常但 worker drained | 任务排队 | deploy smoke 不再误判，Admin 诊断 | 用户端需解释排队原因 |
| qwen executor 卡死 | 单任务无进展 | executor registry + timeout | per-run process/container 要继续硬化 |

结论：条件通过。事故路径已有设计覆盖，但 rollback、projection rebuild、channel signature、planner budget 是 V2 实现必须考虑的工程项。

## 第十二轮：Go / No-Go 判定

### Go 条件

以下可以进入实现：

- V2-P1 Workspace。
- Task wrapper。
- Task event projection。
- Result page。
- Admin/Ops/Audit 信息架构整理。

### No-Go 条件

以下条件满足前，不得开放多用户公网使用：

- 没有用户/项目级数据隔离。
- 没有 CSRF。
- 没有 session token_version。
- 没有登录限速。
- IM permission 没有签名验证和身份映射。
- Artifact 下载未做授权过滤。
- Permission decision 未完整审计。

### 最终结论

```text
V2 方案方向：Go
V2-P1 实现：Go
多用户公网开放：No-Go until V2-P2 complete
企业租户能力：No-Go until storage/secrets/tenant isolation hardening
```

## 审计后修订建议

建议将以下内容补回 V2 实施 backlog：

| 优先级 | 建议 | 原因 |
| --- | --- | --- |
| P0 | Artifact 下载授权过滤 | 防止跨用户数据泄漏 |
| P0 | Permission card 强制风险字段 | 防止用户盲批 |
| P0 | Task/Run/Artifact user/project 字段 | 多用户隔离基础 |
| P1 | `completed_with_warnings` / `partial` 状态 | 避免虚假完成 |
| P1 | Planner budget/step limit | 防止自动规划失控 |
| P1 | Projection rebuild | 防止 UI 投影丢失 |
| P1 | Channel signature verification | 防止 IM webhook 伪造 |
| P2 | Workspace snapshot/rollback | 降低危险操作损失 |
| P2 | Doctor / support bundle | 降低部署支持成本 |

## 审计结论归档

V2 总体设计没有发现需要推翻的结构性问题。当前方案的关键优点是：

1. 用户端和后台端分离，符合最终用户需求。
2. Task 产品层不破坏现有 runtime。
3. 审计事实源仍保留在 canonical events。
4. 调度、隔离、worker、executor 能力不退化。
5. 分阶段路线可实施。

当前方案的关键风险是：

1. V2-P1 做完后容易误以为已经可多用户开放。
2. IM/App 入口如果过早上线，可能绕过认证和 CSRF 边界。
3. Artifact 和 permission 是最容易发生数据泄漏或越权的地方。
4. Planner 自动编排必须有预算和步骤上限。

因此最终建议：

- 先实现 V2-P1，但只面向 owner/单用户或受控小团队。
- V2-P2 完成前，不开启公开注册或多租户公网使用。
- 所有用户端简化都必须能回链后台审计事实。
