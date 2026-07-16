# 产品与架构审计

这份审计记录当前产品体验和系统设计的真实状态，避免把实现基础误判为已经完成的商业级平台。

## 总体判断

AgentFlow 当前已经适合内部自托管 beta、真实 qwen 单任务验证、执行单元接入、基础 Channel smoke 和 Admin 运维验证。

它还不适合无保留地作为商业级多租户 SaaS 开放。主要原因是企业身份、项目成员共享、细粒度 artifact 授权、对象存储、灰度发布、完整合规审计和大规模 HA 仍需要继续打磨。

## 产品经理视角

好的变化：

- 默认入口已经从运行时控制台切到 Client Task。
- Task Detail 把 Agent Chat 放到核心位置。
- Admin 承担配置、运维、审计，而不是压到普通用户首屏。
- 文档已按当前产品重组，不再让用户在历史版本和早期文档里迷路。

仍要优化：

- 失败任务需要更强的“原因 + 建议动作”摘要。
- Channel 没配置时，用户应看到明确禁用态，而不是猜测。
- 最终产物应有更像产品结果页的呈现，而不是只列文件。
- 真实 CLI、fake、协议模拟的状态要更明确。

## 小白用户视角

小白用户应该能完成：

1. 登录。
2. 点模板或输入目标。
3. 提交任务。
4. 在 Agent Chat 看进展。
5. 下载结果。

当前已基本可完成，但仍有两个风险：

- 任务失败后，小白用户仍会被迫看事件和日志。
- Admin 名词仍偏工程化，不适合非技术 owner 长期使用。

## 专业用户视角

专业用户关心：

- 是否能指定 qwen/codex/claude/opencode。
- 是否能看到每个 Agent 的事件和产物。
- 是否能配置 DAG、执行单元和资源策略。
- 是否能重试、回放、审计。
- 是否能接入 NAS、Docker、ECS 和 IM。

当前基础链路具备，但生产级使用还需要：

- 更完整的调度策略。
- 更强的 workspace 隔离。
- 更清楚的 adapter capability discovery。
- 更成熟的 Temporal durable workflow 替换路径。

## 系统设计视角

架构分层是合理的：

- Channel 层负责入口和通知。
- Client/Admin 是两个产品视图。
- Control plane 负责任务、编排、权限、审计。
- State 层负责持久化和恢复。
- Execution 层负责真实 CLI 和隔离 workspace。

主要风险：

| 风险 | 当前缓解 | 后续要求 |
| --- | --- | --- |
| 2C2G 资源不足 | 推荐 capacity=1，CI 不跑在 VPS | 控制面和 worker 拆分 |
| 长任务恢复 | 内置 durable engine 和 replay | Temporal profile 生产化 |
| 多租户边界 | Admin/RBAC foundation | artifact、permission、channel 全链路隔离 |
| CLI 不稳定 | adapter 标准化和日志审计 | capability discovery 和故障分类 |
| Channel 安全 | 文档要求边缘签名校验 | 平台签名校验组件产品化 |

## 当前上线边界

可以上线给内部团队试用：

- 自托管 owner 明确。
- 用户规模小。
- 任务不涉及强合规数据。
- qwen/codex/claude/opencode 并发受控。
- 管理员能处理失败和排障。

不建议直接开放：

- 公共注册。
- 不可信租户。
- 高并发真实 CLI。
- 强合规客户。
- 没有备份恢复演练的生产数据。
