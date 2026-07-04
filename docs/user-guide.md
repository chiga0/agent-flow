# 使用管理台

这篇按页面说明日常怎么用 AgentFlow。普通用户优先使用工作台发起任务、看进度和拿结果；管理员再进入 Overview、Runs、Missions、Units、Executors、Access、Operations 做后台治理。

## 登录

打开管理台地址：

```text
https://<你的域名>/cloud-agents/
```

登录使用部署时配置的邮箱和密码：

- 邮箱：`RUNTIME_AUTH_EMAIL`
- 密码：优先使用 `RUNTIME_AUTH_PASSWORD`；如果没配置，则兼容使用 `RUNTIME_BASIC_AUTH_PASSWORD`

当前是本地邮箱账户体系，不是浏览器 Basic Auth，也还没有 SMTP 邮件验证、邮箱验证码或找回密码。

## Workspace

Workspace 是默认首页，也是普通用户的主要入口。

你可以：

- 用自然语言描述任务目标。
- 选择单 Agent 或多 Agent 编排模式。
- 可选指定 adapter 和已有工作区。
- 查看最近任务、进行中任务、需要处理的任务和已完成任务。
- 打开 Task Detail 查看实时进展、追加消息、下载结果和产物。

推荐流程：

1. 第一次部署后，adapter 先选 `fake`，输入短目标，例如 `请回复 OK`。
2. 确认任务进入详情页，并能看到 Timeline、Result、Artifacts。
3. fake 通过后，再选择 `qwen` 跑真实轻量任务。
4. 长任务或机器资源紧张时，先在 Units 注册远程 worker，再发起真实任务。

Workspace 背后的 API 是 `/tasks`。它会把底层 run 或 mission 投影为统一的用户任务，所以普通用户不需要先理解 run、worker、executor、lease 等技术参数。

当前 Workspace 已开始按登录用户隔离：普通 `member` 只能看到自己创建的 task；`owner` 可查看全部 task；后台 operator/auditor 仍通过后台入口做排障和审计。项目成员级共享属于后续 V2-P2 子阶段。

## Task Detail

Task Detail 是用户查看单个任务的主页面。

你会看到：

| 区域 | 用途 |
| --- | --- |
| 任务状态 | 显示 queued、running、blocked、completed、failed、cancelled |
| Timeline | 按用户可读语言展示环境准备、Agent 启动、权限请求、模型输出和完成状态 |
| Follow up | 单 Agent 任务仍在运行时，可以追加上下文或新要求 |
| Result | 汇总最终结果或当前摘要 |
| Artifacts | 下载 final report、diagnostics、事件文件等产物 |
| 后台链接 | owner/operator 可跳到对应 Run 或 Mission 做审计排障 |

如果任务一直 running，优先看：

1. Timeline 是否还有新进展。
2. 是否出现 `attention` 或权限处理提示。
3. Result 是否已有中间摘要。
4. Artifacts 是否已经生成报告或 diagnostics。
5. 需要更细排障时，再进入后台 Run Detail、Executors 或 Units。

## Overview

Overview 用来看系统是否健康：

- 当前 run、mission、queue、worker 的概况。
- 最近任务。
- 失败、运行中、等待状态。
- 成本和预算基础信息。

如果你觉得系统“没反应”，普通用户先看 Task Detail；管理员再看 Overview、具体 Run Detail 或 Units。

## Runs

Runs 是后台运行视图，用来创建和查看单个底层 run。普通用户日常应优先使用 Workspace；Runs 更适合部署验证、qwen 排障和审计。

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
| Artifacts | 预览或下载 diagnostics、executor 日志、final report、events 等文件 |
| 审计下载 | 固定下载 events、diagnostics、audit bundle |
| Audit Bundle | 下载完整审计包 |

Artifact 区的小型文本文件可以直接预览，例如 `.json`、`.jsonl`、`.md`、`.txt`、`.log`。大文件或二进制文件只保留下载，避免浏览器卡顿。

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

这里的术语关系是：

- 执行单元：管理台里的产品视图。
- Worker：部署在 VPS、NAS、本地电脑或主控机上的后台进程。
- 一次性令牌：注册 worker 时创建的 `workers:*` API token，明文只显示一次。

注册步骤：

1. 在 Units 页面填写 Unit ID、控制地址、容量和资源标签。
2. 点击 Generate。
3. 优先复制“无需本地源码”命令，替换 `root@<worker-ip>` 和 `/path/to/key.pem`。
4. 在你的本地机器执行该命令，它会通过 SSH 安装远端 worker。
5. 回到 Units 页面刷新，确认心跳、容量和 adapter 标签出现。

“已有本地源码”命令适合你已经 clone 本仓库并在仓库根目录执行；“无需本地源码”命令会先从 GitHub 下载部署脚本，所以新机器接入更直观。远端 VPS 仍会 clone 本仓库，因为 worker service、运行时代码和 systemd 文件来自仓库。

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
- registry 配置和 lease 计数。

执行单元/worker 是接任务的机器或进程；executor 是 worker 为某次 run 启动或复用的真实运行实例；registry 是控制面保存 executor 租约和状态的台账。

如果 fake run 正常但 qwen run 失败，优先看这里。

## Access

Access 用来管理 API token 和基础访问能力。

建议：

- 只有 `owner` 可以在页面内创建登录用户、项目和 API token。
- `member` 用于普通用户的 Workspace 主流程，只能看到自己创建的 task。
- `operator` 用于日常创建/取消 run、mission 和处理权限请求。
- `auditor` 用于只读查看事件、artifact、审计材料和状态。
- worker token 使用 `workers:*` scope。
- 自动化脚本按需创建最小 scope token。
- token 明文只显示一次，创建后立即妥善保存。
- 泄露或不用的 token 及时 revoke。

创建登录用户时，进入 `Access -> Users`，填写邮箱、初始密码和角色。当前仍是本地邮箱账户体系；管理员可以把邮箱标记为已验证，但还没有 SMTP 邮件验证、邀请邮件和忘记密码流程。

## Operations

Operations 面向运维：

- 创建 backup。
- 运行 failure drill。
- 查看 runtime status。
- 查看 P5 evaluation 和 cost/budget。

部署后建议至少跑一次 smoke/drill，确认备份、监控和恢复材料能正常生成。
