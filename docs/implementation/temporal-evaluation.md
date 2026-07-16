# Temporal 适配方案

AgentFlow 支持轻量内置 durable workflow，也预留 Temporal profile。是否启用 Temporal 取决于任务时长、人工审批、失败恢复和水平扩展要求。

## 1. 什么时候需要 Temporal

建议启用 Temporal 的场景：

- 任务持续数小时到数天。
- DAG 中有多次人工审批。
- 需要可靠 timeout、retry、resume。
- 多个 worker 水平扩展。
- 任务失败后需要明确恢复点。
- 管理员需要可视化 workflow history。

不一定需要 Temporal 的场景：

- 单机自托管。
- 低并发。
- 只跑 fake smoke 或轻量 qwen。
- 任务失败后人工重跑即可接受。

## 2. 推荐边界

Temporal 负责 workflow durability，不负责替代 AgentFlow 的产品模型。

| 职责 | 所属 |
| --- | --- |
| Task、Tenant、RBAC、Channel、Artifact | AgentFlow 控制面 |
| DAG 状态、Activity retry、timeout、resume | Temporal profile |
| CLI adapter 执行 | Execution Unit / Worker |
| 权限审批和审计 | AgentFlow 控制面 |

## 3. Workflow 映射

```mermaid
flowchart LR
  Task["Task"] --> Workflow["Temporal Workflow"]
  Workflow --> Plan["Plan Activity"]
  Workflow --> A1["Agent Activity A"]
  Workflow --> A2["Agent Activity B"]
  A1 --> Eval["Evaluate Activity"]
  A2 --> Eval
  Eval --> Final["Finalize Activity"]
```

每个 Agent Activity 只负责向 AgentFlow 请求执行单元并等待结果。真实 CLI 仍由 worker/adapter 执行，事件和 artifact 仍写回 AgentFlow。

## 4. HA profile 配置

典型配置：

```bash
V2_WORKFLOW_ENGINE=temporal
TEMPORAL_TASK_QUEUE=agentflow-v2
V2_QUEUE_URL=redis://redis:6379/0
V2_DATABASE_URL=postgresql://agentflow:${POSTGRES_PASSWORD}@postgres:5432/agentflow
V2_WORKER_REPLICAS=2
V2_WORKER_CONCURRENCY=2
```

这些环境变量名称目前保留 `V2_` 前缀作为实现兼容，不表示用户需要选择不同产品版本。

## 5. 接入门禁

启用 Temporal profile 前必须验证：

- fake task 通过。
- 至少一个真实 adapter task 通过。
- worker 重启后 workflow 可恢复。
- 人工审批等待期间 workflow 不丢失。
- retry 不重复写不可幂等 artifact。
- audit bundle 能关联 workflow history。
