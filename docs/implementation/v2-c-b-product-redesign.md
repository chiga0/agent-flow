# AgentFlow V2 C/B 双端产品重设计

> 日期：2026-07-06  
> 目标：把 AgentFlow 从“技术控制台优先”重构为“两套独立产品”：C 端是不用学习概念的 Agent Chat 工作区；B 端是面向 owner/operator/auditor 的管理、配置、审计与回放后台。

## 1. 用户画像

| 端 | 用户 | 目标 | 不应该看到 |
| --- | --- | --- | --- |
| C 端用户端 | 个人用户、小团队成员、业务人员 | 直接描述需求，查看进展，处理必要确认，拿最终结果 | adapter、worker、executor、run id、队列租约、审计包、资源参数 |
| B 端管理端 | owner、operator、auditor、平台维护者 | 管理用户、worker、executor、成本、任务事实、审计和恢复 | 面向普通用户的极简 Chat 入口不应限制后台深度 |

## 2. 产品原则

### C 端

- 首屏就是 Chat/任务输入，不做营销页。
- 默认由系统选择单 Agent 或多 Agent 编排，用户只表达目标。
- 用户看到“AI 正在处理需求”的进展，不需要理解 run、mission、worker。
- 任务详情只保留对用户有价值的四件事：当前状态、实时进展、继续补充、最终结果/产物。
- 移动端优先保证输入、进度和待处理事项可见。

### B 端

- 独立 `/admin/*` 信息架构。
- 保留运行时事实：runs、missions、workers、executors、events、artifacts、audit bundle。
- owner/operator/auditor 看到不同能力。
- 后台必须支持排障、审计、回放、备份和部署验证。
- 不以牺牲事实可追溯为代价做前端简化。

## 3. 信息架构

```text
C 端
  /
    Chat 创建任务
    进行中任务
    待处理任务
    最近任务
  /tasks/:taskId
    任务对话
    实时进展
    继续补充
    结果与产物

B 端
  /admin
    Overview
  /admin/runs
  /admin/missions
  /admin/units
  /admin/executors
  /admin/profiles
  /admin/access
  /admin/operations
```

旧 `/runs`、`/missions`、`/operations` 等路径短期保留为兼容入口，但不再作为主导航。

## 4. 当前实施状态

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| P1：路径与导航隔离 | in progress | 新增 `/admin/*`，C 端隐藏后台导航 |
| P1：C 端 Chat 首页 | in progress | 首页改为 Chat composer，隐藏 adapter/mode/workspace |
| P1：C 端任务详情去技术化 | in progress | 移除后台 Run/Mission 直跳，保留进度、结果、产物 |
| P2：Admin 内部链接收敛 | planned | 后台内部所有 run/mission 链接迁到 `/admin/*` |
| P3：任务投影增强 | planned | 多 Agent 子任务聚合为用户可读进展 |
| P4：权限与结果体验 | planned | 用户端审批卡片、最终结果页、分享/导出 |
| P5：线上 E2E | planned | 对公网 C 端和 B 端分别做登录、建任务、查看后台的 E2E |

## 5. 多轮 Review

### 产品 Review

通过。C 端首屏以 Chat 输入为主，降低学习成本；B 端独立 Admin 保留治理深度。

剩余风险：如果任务详情仍暴露底层 event 名称，会继续让用户感到“技术控制台化”。后续需要把 `TaskEvent` 投影成自然语言进展。

### 架构 Review

通过。Task 作为 C 端产品实体，Run/Mission 作为 B 端事实实体，分层正确。

剩余风险：旧路径兼容会造成内部链接分叉。P2 必须把后台内部链接全部迁移到 `/admin/*`。

### 安全 Review

条件通过。C 端隐藏后台入口不是权限边界，真正边界仍必须由 API RBAC、artifact 授权和 task 归属过滤保证。

剩余风险：多租户开放前必须完成 V2-P2 安全项，包括 CSRF、token_version、artifact 授权过滤、permission decision 审计。

### E2E Review

当前必须覆盖：

- C 端首页默认没有 Runs/Executors/Access 等后台导航。
- C 端可以输入任务并进入 `/tasks/:taskId`。
- B 端 owner 可以进入 `/admin` 并看到 Runs/Workers/Executors 等后台导航。
- 移动端 C 端输入和开始任务按钮可见。

后续必须补齐：

- 真实 mission 中多个 task/profile/run_id 聚合展示。
- C 端审批后状态消除待处理。
- Admin 审计包下载和回放入口。
