# 外部方案对比与多方向审计

> 调研日期：2026-06-30  
> 目标：在已经确定 `qwen serve` 作为第一版 SAEU 实现后，再对比当前更成熟或相近的方案，并用对比审计、正向审计、无方向审计、反向审计验证当前方案是否需要调整。

## 总结结论

当前方案不需要推翻。更稳妥的调整是：

- 保留 `qwen serve` 作为第一版 SAEU 实现。
- 把 SAEU contract 做成稳定内部边界，并向 ACP-compatible runtime adapter 收敛，避免绑定 qwen 私有 API。
- 允许未来替换三类组件：
  - 执行器：Qwen Code、Claude Code、Codex、OpenCode、OpenHands、自研 worker。
  - 沙箱：Docker/rootless Docker、E2B、Daytona、OpenHands Runtime、microVM。
  - 编排器：Postgres queue、Temporal、LangGraph/LangSmith。
- A2A 放在系统边界，不取代内部 ACP/SAEU contract。
- Roadmap 中加入“替代方案评估里程碑”，避免后续架构锁死。

一句话：**当前路线是低资源 VPS 条件下可实施性最高的路线；外部成熟方案更适合成为后续替换模块，而不是第一天整体替换。**

## 调研对象

| 类别 | 方案 | 价值点 | 对当前方案的启发 |
| --- | --- | --- | --- |
| 托管 Agent Runtime | AWS Bedrock AgentCore | Runtime、Gateway、Memory、Identity、Observability、内置工具 | 证明 Agent Runtime 应拆成运行、工具、身份、观测、记忆等模块 |
| 托管 Agent 平台 | Microsoft Foundry Agent Service | 托管部署、身份、memory、observability、任意框架/模型 | 适合企业云上生产，但不适合 1-2 台 VPS 起步 |
| 托管 Agent Runtime | Google ADK + Agent Runtime | ADK 开发、多 Agent、Agent Runtime 部署治理 | 适合 Google Cloud 生态，可作为未来云端迁移参考 |
| Agent SDK | OpenAI Agents SDK | Runner、tools、guardrails、handoffs、sessions、tracing | 可作为业务 Agent SDK 参考，但不替代 coding agent harness |
| 可恢复编排 | LangGraph / LangSmith | durable execution、streaming、human-in-the-loop | 可作为 supervisor/workflow 层候选 |
| Durable workflow | Temporal | 长流程、Signal/Query/Update、Activity retry | 适合后期接管 mission/run lifecycle |
| 云沙箱 | E2B | 为 Agent 提供安全云端 sandbox、支持 coding agents | 可替代自建 Docker sandbox |
| 云沙箱 | Daytona | 快速、可恢复、隔离的 AI agent sandbox | 可作为高并发/更强隔离替代 |
| Coding Agent 平台 | OpenHands / OpenHands Enterprise | 自托管 coding agents、runtime、event-sourced replay | 可作为执行器或竞品参考 |

## 对比审计

### 评价维度

| 维度 | 说明 |
| --- | --- |
| 低资源可实施性 | 是否适合 1-2 台小 VPS 起步 |
| Coding Agent 贴合度 | 是否天然支持代码编辑、shell、git、diff、review |
| 审计与重放 | 是否支持事件、trace、artifact、deterministic replay |
| 可恢复性 | 是否支持断线、崩溃、长任务恢复 |
| 权限与 HITL | 是否支持工具审批、人类介入 |
| 沙箱隔离 | 是否提供强隔离工作区 |
| 协议互操作 | 是否适合 ACP/A2A/MCP |
| 迁移成本 | 对当前方案的替换成本 |

### 对比矩阵

| 方案 | 低资源 | Coding 贴合 | 审计重放 | 恢复 | 权限/HITL | 沙箱 | 互操作 | 判断 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 当前 qwen serve SAEU | 高 | 高 | 中，需外部补齐 | 中，需外部补齐 | 高 | 中 | 中高，需 `/acp` 收敛 | MVP 主线 |
| AWS Bedrock AgentCore | 低 | 中 | 高 | 高 | 高 | 高 | 中 | 企业 AWS 路线 |
| Microsoft Foundry Agent Service | 低 | 中 | 高 | 高 | 高 | 中 | 中 | Azure 企业路线 |
| Google ADK + Agent Runtime | 低 | 中 | 高 | 高 | 高 | 中 | 中 | Google Cloud 路线 |
| OpenAI Agents SDK | 中 | 中 | 高 | 中 | 高 | 低 | 中 | 业务 Agent SDK，不是 coding runtime |
| LangGraph/LangSmith | 中 | 中 | 高 | 高 | 高 | 低 | 中 | Supervisor/workflow 候选 |
| Temporal | 中 | 低 | 中 | 高 | 高 | 低 | 高 | 长流程编排候选 |
| E2B | 中 | 高 | 中 | 中 | 低 | 高 | 中 | 沙箱替代候选 |
| Daytona | 中 | 高 | 中 | 中 | 低 | 高 | 中 | 沙箱替代候选 |
| OpenHands Enterprise | 中 | 高 | 高 | 中 | 中 | 高 | 中 | 执行器/平台替代候选 |

### 对比结论

当前方案的优势：

- 最贴合用户当前资源约束。
- 能直接复用 Qwen Code 的 coding harness。
- 可快速实现单 Agent 云端执行单元。
- 不绑定 AWS/Azure/GCP。
- 后续可逐步接入 ACP Streamable HTTP、A2A、MCP、Temporal、外部沙箱。

当前方案的短板：

- qwen serve 仍是 experimental/local-first，需要外部 Supervisor 补强。
- 审计、重放、恢复不能依赖 qwen 自身 event ring。
- Docker 在恶意代码场景下不是强安全边界。
- 多 Agent 编排需要自建 Run Manager 和 Event Store。

外部方案带来的改进方向：

- 如果沙箱成为瓶颈，优先评估 E2B/Daytona，而不是自研 microVM。
- 如果 mission/run workflow 变复杂，引入 Temporal 或 LangGraph，而不是把状态机继续堆进 Supervisor。
- 如果进入企业云场景，可评估 AgentCore/Foundry/Google Agent Runtime。
- 如果需要另一个 coding agent runtime，可把 Codex、Claude Code、OpenCode 或 OpenHands 作为 SAEU adapter 试点。

## 正向审计

正向审计从目标出发，检查当前方案是否满足目标。

| 目标 | 当前方案能力 | 审计结论 |
| --- | --- | --- |
| 单 Agent 可长期运行 | qwen serve + Supervisor + Event Store | 可行 |
| 可外部通信 | SAEU contract + ACP/REST/SSE + A2A Gateway | 可行 |
| 实时状态 | qwen SSE -> canonical events -> Run Manager SSE | 可行 |
| 权限请求 | qwen permission mediation -> Permission Service | 可行 |
| 审计 | canonical events + artifact package | 可行 |
| 重放 | UI replay、transcript replay、后续 deterministic replay | 可行，但分阶段 |
| 可恢复 | Last-Event-ID、load/resume、workspace snapshot、Supervisor recovery | 可行，但必须外部持久化 |
| 多 Agent 编排 | Project/Supervisor + SubAgent + SAEU queue + artifact 协作 | 可行 |
| 小 VPS 起步 | 并发 1-2，Docker sandbox，Postgres queue | 可行 |
| 未来替换方案 | ACP-compatible SAEU adapter 边界 | 可行 |

正向审计结论：当前方案满足 MVP 到 Beta 的目标，但必须按 Roadmap 先实现 Event Store、Artifact Store、Permission Service 和 Supervisor，而不是只启动 qwen serve。

## 无方向审计

无方向审计不从目标出发，而是从组件、边界和随机故障点横向扫描。

| 区域 | 可能问题 | 缓解 |
| --- | --- | --- |
| qwen serve | daemon experimental，API 可能变动 | adapter 封装；版本 pin；capabilities preflight |
| ACP adapter | 标准仍在演进，Streamable HTTP 未必所有 Agent 支持 | 先兼容 qwen REST/SSE，新增 `/acp` POC，adapter 分层 |
| Event Store | 写入失败导致无审计执行 | 写失败则 pause/cancel run，不能继续 |
| SSE | event ring gap | 外部 canonical event store；gap event；load/resume 补救 |
| Permission | 审批超时或多客户端冲突 | timeout 默认 deny/cancel；记录投票策略 |
| Workspace | 并发写冲突 | 每个 coder 独立 worktree；merge 单独执行 |
| Sandbox | Docker escape 或误挂载 | 非 root、cap drop、不挂 Docker socket；高风险任务独立 VPS |
| Model Proxy | key 泄漏或成本失控 | scoped token、预算、审计、限流 |
| MCP | 工具权限过宽 | MCP Gateway 登记、按 run 注入最小权限 |
| Artifact | 大文件撑爆 VPS | retention policy、压缩、外部对象存储迁移点 |
| Supervisor | 规则复杂化 | 到阈值后迁移 Temporal/LangGraph |

无方向审计结论：最大风险不在 qwen serve 本身，而在“外部补强组件是否真的实现”。Roadmap 必须把 Event Store、Permission Service、Artifact Collector 列为早期硬化阶段，并在这些能力完成前限制多 Agent 扩张。

## 反向审计

反向审计从失败事故倒推当前设计能否承受。

| 事故 | 如果发生会怎样 | 当前方案是否能处理 | 必须动作 |
| --- | --- | --- | --- |
| qwen daemon 崩溃 | session_died，SSE 终止 | 能检测，恢复依赖外部状态 | 保存 crash diagnostics，尝试 load/resume |
| Supervisor 重启 | SSE 订阅丢失 | 能处理 | 扫描 running runs，Last-Event-ID reconnect |
| VPS 重启 | 容器可能消失 | 部分处理 | systemd + DB running scan + recovery policy |
| 审批没人响应 | run 卡住 | 能处理 | permission timeout，默认 cancel/deny |
| qwen event ring 被覆盖 | 中间事件丢失 | 可检测 | 外部 Event Store 是唯一审计源 |
| Agent 误删 workspace | run 失败 | 部分处理 | git worktree + checkpoint + artifact |
| Agent 泄漏 key | 严重事故 | 可预防 | key 不进容器，model proxy only |
| 多 Agent patch 冲突 | merge 失败 | 能处理 | 独立 worktree + merge agent +人工审批 |
| 模型 API 限流 | run 失败或变慢 | 可处理 | model proxy retry/backoff/budget |
| DB 不可用 | 系统不可审计 | 高风险 | 暂停新 run；running run 进入 degraded |

反向审计结论：当前方案能覆盖大部分预期事故；唯一不能接受的是“Event Store 不可用时继续执行”。这条必须作为硬性系统规则。

## 是否存在更好的整体替代方案

如果约束是“1-2 台小 VPS、希望先落地 coding agent、多 Agent 后续演进”，没有看到明显优于当前路线的整体替代方案。

更好的单点替代如下：

| 替代点 | 更好的候选 | 何时替换 |
| --- | --- | --- |
| 沙箱 | E2B / Daytona | Docker 资源隔离、恢复、并发、恶意代码风险成为瓶颈 |
| 长流程编排 | Temporal | mission 跨小时/跨天、审批等待、fan-out/fan-in 复杂 |
| Agent workflow | LangGraph/LangSmith | Supervisor 需要状态图、HITL、durable execution |
| 企业云托管 | AgentCore / Foundry / Google Agent Runtime | 进入企业云、合规和托管预算充足 |
| Coding Agent 平台 | OpenHands Enterprise | 希望直接采用已有自托管 coding agent 平台 |
| 业务 Agent SDK | OpenAI Agents SDK | 要做非 coding 的业务 agent、handoff、guardrails、tracing |

## 对当前方案的修订建议

需要修订：

- Roadmap 中加入状态跟踪。
- Roadmap P2 必须包含 Event Store、Permission Service、Artifact Collector。
- Roadmap P5 增加 E2B/Daytona sandbox adapter 评估。
- Roadmap P5 增加 Temporal/LangGraph orchestrator adapter 评估。
- Roadmap P5 增加 A2A Gateway 评估。
- Roadmap P5 增加 ACP Streamable HTTP adapter 评估。
- 文档中明确 SubAgent 与 SAEU 的边界。

不需要修订：

- 不需要放弃 qwen serve SAEU。
- 不需要第一天上 AgentCore/Foundry/Google Agent Runtime。
- 不需要第一天上 Temporal。
- 不需要从头实现 coding agent。
- 不需要把每个 SubAgent 都拆成独立 SAEU。

## 参考资料

- [AWS Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AWS Bedrock AgentCore Observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- [Microsoft Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/overview)
- [Google Agent Development Kit](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk)
- [Google Agent Runtime](https://adk.dev/deploy/agent-runtime/)
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/agents/)
- [OpenAI Agents SDK Tracing](https://openai.github.io/openai-agents-python/tracing/)
- [LangGraph Overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangSmith Deployment](https://www.langchain.com/langsmith/deployment)
- [E2B Documentation](https://e2b.dev/docs)
- [E2B Coding Agents](https://e2b.dev/docs/use-cases/coding-agents)
- [Daytona](https://www.daytona.io/)
- [OpenHands Enterprise](https://docs.openhands.dev/enterprise)
- [Agent Client Protocol](https://agentclientprotocol.com/get-started/introduction)
- [ACP Streamable HTTP & WebSocket Transport RFD](https://agentclientprotocol.com/rfds/streamable-http-websocket-transport)
