# AgentFlow V2 实施 Roadmap

> 日期：2026-07-04  
> 状态：`in_progress`  
> 目标：把 V2 从方案文档推进为可连续交付的产品工程。每个阶段都必须经过实现、代码 review、产品审计、架构审计、测试补强和 E2E 验收，不能只做文档或 UI。

## 0. 交付纪律

V2 后续开发按“阶段切片”推进。每个切片完成后必须留下证据：

| 门禁 | 必须完成的事 |
| --- | --- |
| Design Review | 本阶段目标、边界、数据模型和降级行为已写入文档 |
| Security Review | 身份、权限、数据隔离、审计记录和敏感信息边界已检查 |
| Product Review | 普通用户默认只看到任务语言，后台技术参数不进入主流程 |
| Architecture Review | Task 产品层不破坏 Run/Mission/Worker/Executor 事实源 |
| Unit/Integration Tests | 后端关键分支和权限边界有测试 |
| Web Tests | 用户入口、状态展示、错误态和角色管控有测试 |
| E2E Tests | 至少覆盖一个真实页面路径，验证移动端或桌面端主链路 |
| Docs Update | 使用说明、架构说明、审计记录和 Roadmap 状态同步更新 |
| CI/CD | Runtime CI、Deploy Runtime、Deploy MkDocs、Runtime Monitor 通过 |

阶段退出前如发现 P0/P1 问题，必须先修复或降级标记，不能继续堆功能。

## 1. 阶段总览

| 阶段 | 目标 | 状态 | 当前判断 |
| --- | --- | --- | --- |
| V2-P0 | 方案、竞品调研、多轮审计 | `done` | V2 方向已从 runtime console 调整为用户任务工作台 |
| V2-P1 | 用户端 Task Workspace | `foundation_done` | 首页、Task BFF、Task Detail、基础测试已落地 |
| V2-P2 | 认证、用户隔离、角色管控 | `in_progress` | P2a 已完成 foundation，P2b-P2e 待推进 |
| V2-P3 | 默认 Agent 编排与自动规划 | `not_started` | 复杂任务自动 mission，简单任务 single run |
| V2-P4 | 文件、Skills、结果页 | `not_started` | 文件作为 task input，Skills registry，结果可消费 |
| V2-P5 | IM/App/移动端入口 | `not_started` | Channel Gateway 不绕过身份和权限 |
| V2-P6 | 后台 Admin/Ops/Audit 重构 | `not_started` | 后台从用户端分离，审计、队列、worker、成本更集中 |
| V2-P7 | 整体验收与可开放边界 | `not_started` | 从设计、架构、用户使用和部署运维做最终审计 |

## 2. V2-P2：认证、用户隔离、角色管控

### 2.1 目标

V2-P2 是真实用户开放前的硬门槛。它解决的问题不是“能不能登录”，而是：

- 用户创建的任务不会被其他普通用户看到。
- owner/admin 可以管理用户、角色、项目和任务边界。
- operator/auditor 只能访问被授权范围。
- 权限审批、artifact、结果读取都能回到真实身份。
- 登录、会话、API token 和后续 IM channel 使用同一套身份模型。

### 2.2 子阶段

| 子阶段 | 交付物 | 状态 | 退出标准 |
| --- | --- | --- | --- |
| P2a | Task created_by/project 绑定与 `/tasks` 过滤 | `foundation_done` | session 用户只能看到自己的 task，owner 可看全部 |
| P2b | 用户管理 UI 强化 | `not_started` | owner 可创建、禁用、改角色、重置密码 |
| P2c | CSRF、改密码、token_version | `not_started` | session 写操作有 CSRF，改密码会使旧 session/token 失效 |
| P2d | Project membership | `not_started` | project member 可见项目任务，非成员不可见 |
| P2e | Artifact/result/permission 全链路隔离 | `not_started` | task detail 相关读取和审批都经过同一访问判断 |

### 2.3 P2a 验收

P2a 的验收重点是先把用户端 Workspace 保护起来：

| 验收项 | 标准 |
| --- | --- |
| 创建任务 | `/tasks` 写入 `created_by`、`project_id`、`visibility` |
| 列表过滤 | 普通用户只看到自己创建的 task |
| 详情过滤 | 普通用户访问他人 task 返回 404 |
| 操作过滤 | 普通用户不能给他人 task 追加消息或取消 |
| owner 视角 | owner 仍能看到全部 task |
| 测试 | runtime integration test + Web/E2E 覆盖 |

## 3. V2-P3：默认 Agent 编排

### 3.1 目标

用户不应先理解 single run 和 mission。系统应根据目标自动选择执行形态：

- 简单问题：single run。
- 多步骤目标：mission。
- 需要审计/测试/报告：planner -> worker -> reviewer -> final report。

### 3.2 实施项

| 项 | 内容 |
| --- | --- |
| Task Planner | 接收自然语言目标，输出 plan 草案、风险、预估步骤 |
| Routing Policy | 根据复杂度、文件、仓库、风险选择 single 或 mission |
| Plan Preview | 用户可在创建前查看将要做什么 |
| Auto Mission | 根据 plan 生成 mission tasks 和 profile |
| Review Gate | 高风险任务默认带 reviewer gate |

### 3.3 审计点

- Planner 输出不能直接成为不可审计的隐式行动。
- 自动 mission 必须保留每个子任务的 profile、输入、artifact handoff。
- 用户看到的是“计划和进度”，后台保留 run/mission/event 事实源。

## 4. V2-P4：文件、Skills 与结果页

### 4.1 目标

让用户能把真实材料交给 AgentFlow，并能消费最终结果：

- 上传文件。
- 选择或自动推荐技能。
- 结果页展示总结、产物、风险、下一步。
- 结果可以分享或导出，但不暴露 audit。

### 4.2 实施项

| 项 | 内容 |
| --- | --- |
| File Input | task 创建时上传文件，进入 artifact/input 区 |
| Skills Registry | 读取 `SKILL.md` 风格的技能描述，作为任务能力选择 |
| Result Summary | 从 final artifact 中抽取摘要、文件、代码 diff、失败原因 |
| Share Link | 只读结果分享，不含后台审计 |
| Retention Policy | task 文件、结果和 audit 保留策略可配置 |

## 5. V2-P5：IM、App 与移动端入口

### 5.1 目标

用户可以从 Web 之外发起和监控任务，但不能绕过权限系统：

- IM 机器人创建 task。
- IM 推送进展和权限请求。
- 用户可在 IM 中 approve once。
- 移动端页面可完成创建、查看、审批、下载结果。

### 5.2 审计点

- Channel identity 必须映射到真实 user/project。
- IM approve 必须写入 permission audit。
- IM 不能返回完整 artifact 或敏感输出，除非策略允许。
- 移动端首屏必须保留当前状态和下一步动作。

## 6. V2-P6：后台 Admin/Ops/Audit 重构

### 6.1 目标

后台要变成系统治理入口，而不是用户默认页面：

- Admin Overview 汇总健康、失败率、队列和成本。
- Workers/Executors 专注执行面排障。
- Audit 可以按 task/user/project/run 查询。
- Access 可以管理用户、项目、角色、token。

### 6.2 退出标准

- 普通用户导航中不出现后台项。
- owner/operator/auditor 看到的后台能力不同。
- 所有后台危险操作有确认、审计和失败反馈。

## 7. V2-P7：整体 Review 与审计

V2 完成后必须从三个视角做最终审计：

| 视角 | 审计问题 |
| --- | --- |
| 设计文档 | 文档是否和真实产品一致，是否有过期描述 |
| 架构设计 | Task/Run/Mission/Worker/Executor 边界是否稳定 |
| 用户使用 | 新用户能否不用理解 runtime 参数完成任务 |
| 安全运维 | 多用户、artifact、permission、token、部署是否闭环 |

最终可开放条件：

1. 用户可从 Workspace 发起任务并拿结果。
2. 普通用户无法看到他人的任务、artifact、audit。
3. owner 可管理用户、角色和项目。
4. 任务有实时进度、权限处理和完成总结。
5. 后台有队列、worker、executor、审计和备份入口。
6. CI/CD 和 Runtime Monitor 长期稳定通过。
