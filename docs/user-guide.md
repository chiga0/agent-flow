# 使用管理台

这篇按页面说明日常怎么用 AgentFlow。第一次使用时，建议先创建 fake run，再尝试 qwen run 和 mission。

## 登录

打开管理台地址：

```text
https://<你的域名>/cloud-agents/
```

登录使用部署时配置的邮箱和密码：

- 邮箱：`RUNTIME_AUTH_EMAIL`
- 密码：优先使用 `RUNTIME_AUTH_PASSWORD`；如果没配置，则兼容使用 `RUNTIME_BASIC_AUTH_PASSWORD`

当前是本地邮箱账户体系，不是浏览器 Basic Auth，也还没有 SMTP 邮件验证、邮箱验证码或找回密码。

## Overview

Overview 用来看系统是否健康：

- 当前 run、mission、queue、worker 的概况。
- 最近任务。
- 失败、运行中、等待状态。
- 成本和预算基础信息。

如果你觉得系统“没反应”，先看 Overview，再进入具体 Run Detail 或 Units。

## Runs

Runs 用来创建和查看单个任务。

推荐流程：

1. adapter 先选 `fake`。
2. 输入短 prompt，例如 `hello runtime`。
3. 创建 run。
4. 打开 Run Detail，确认 Agent Chat、Event Stream、Artifacts 都有内容。
5. fake 通过后，再创建 `qwen` run。

不要一开始就用复杂 qwen 任务验证部署。fake run 能帮你先排除登录、API、队列、事件流、前端和 artifact 主链路问题。

## Run Detail

Run Detail 是最重要的页面。

你会看到：

| 区域 | 用途 |
| --- | --- |
| Agent Chat | 看模型输出、工具事件摘要、warning、error |
| Composer | run 仍可交互时继续追加输入 |
| Permission | 处理 pending permission request |
| Event Stream | 查看底层事件，用于排障和审计 |
| Artifacts | 下载 diagnostics、executor 日志、final report |
| Audit Bundle | 下载完整审计包 |

如果 run 一直 running，优先看：

1. Agent Chat 是否还有新输出。
2. 是否出现 permission action bubble。
3. Event Stream 最后一条 event 是什么。
4. Artifacts 里是否有 `diagnostics.json` 或 `executor.stderr.log`。
5. Executors 页面对应 lease 是否 failed、orphaned 或一直 running。

## Missions

Mission 用来执行复杂任务。

常见策略：

| 策略 | 适合场景 |
| --- | --- |
| `sequential` | 按阶段串行完成 |
| `fanout` | 多个子任务并行后汇总 |
| `custom` | 自定义 DAG |

Mission Detail 会展示 task DAG、每个 task 对应的 run、mission events、artifacts 和 reviewer gate 状态。你可以从 mission 跳到子 run 查看更细的 Agent Chat。

## Units

Units 用来管理 worker。

你可以：

- 查看 worker 心跳和资源水位。
- 生成远程 worker 注册命令。
- Drain 一个 worker，让它不再接新任务。
- Resume 一个 worker，让它重新接任务。
- Retry worker 上卡住的任务。

2C2G VPS 建议：

- `capacity=1` 起步。
- 只作为 worker 或公网边缘，不建议同时跑控制面、qwen、构建和多个任务。
- 看到内存、swap、磁盘或 load 长期偏高时，先 drain，再排查。

## Executors

Executors 用于排查 qwen。

重点看：

- qwen executor strategy。
- active/failed lease。
- pid、port、workspace。
- stdout/stderr artifact。
- last error。

如果 fake run 正常但 qwen run 失败，优先看这里。

## Access

Access 用来管理 API token 和基础访问能力。

建议：

- worker token 使用 `workers:*` scope。
- 自动化脚本按需创建最小 scope token。
- token 明文只显示一次，创建后立即妥善保存。
- 泄露或不用的 token 及时 revoke。

## Operations

Operations 面向运维：

- 创建 backup。
- 运行 failure drill。
- 查看 runtime status。
- 查看 P5 evaluation 和 cost/budget。

部署后建议至少跑一次 smoke/drill，确认备份、监控和恢复材料能正常生成。
