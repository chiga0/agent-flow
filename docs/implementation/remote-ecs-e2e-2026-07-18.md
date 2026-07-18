# 远端 ECS 执行单元 E2E 验收记录（2026-07-18）

## 验收范围

本轮以本地 Docker AgentFlow 为控制面、2C2G ECS 为执行面，真实运行 `qwen-code`。验收不使用 fake adapter，覆盖从 Client 创建会话、V2 Task 规划、持久队列、反向 SSH 通道、远端 worker、loopback Qwen daemon、审批恢复、产物回传到移动端状态快照的完整链路。

## 已验证结果

杭州执行单元 `ecs-hz` / `worker-ecs-hz` 已注册并保持 active，固定 `capacity=1`：

- 连续完成 2 轮五类业务任务，共 10 个场景、14 个真实远端 Qwen run；多阶段研究每轮由 3 个 Agent 执行。
- 代码审计、运维巡检、多阶段研究、文件生成和高风险审批均完成；高风险任务在批准前为 `waiting_user`，批准后才由远端 worker 恢复。
- 主动中断反向通道并重启 worker/Qwen 后，心跳和健康检查恢复，第二轮任务全部通过。
- 浏览器桌面端明确选择 `qwen-code + ecs-hz` 后完成真实任务；移动端 390×844 视口下，会话导航、决策台、最近完成、审批历史和“意图—证据—影响面”详情可用。
- 两个生成文件已在 ECS 工作区落盘、重新读取且非空，权限归属为 `cloudagents`。

## 部署过程发现并修复的问题

1. Debian `npm` 会额外安装约 500 个包，不适合 2C2G 节点。部署脚本改为下载官方 Node.js 22 归档并校验 SHA-256。
2. ECS 到 GitHub 的 HTTP/2 连接偶发 framing error。Git 同步改用 HTTP/1.1、浅克隆、独立超时和三次重试，并清理失败的半成品目录。
3. Bash 参数默认值 `${VAR:-{}}` 会在该写法中留下额外右花括号，导致 worker 元数据 JSON 启动失败。现改为显式空值分支并使用精确的 `'{}'`。
4. 重试函数原先在 `if` 之后读取 `$?`，会丢失真实失败码。现于 `else` 分支立即保存退出码。
5. 部署脚本现会等待 Qwen 健康和 worker 心跳后才报告成功，HTTP 探测包含连接和总超时；失败部署的 root 临时凭据文件会清理。

## 安全与资源审计

- worker 与 Qwen 均以 `cloudagents` 非登录用户运行，启用 `NoNewPrivileges`、`PrivateTmp` 和 `ProtectSystem=full`。
- Qwen 仅监听 `127.0.0.1:4210`，反向 SSH 仅监听 ECS `127.0.0.1:18765`。
- worker/Qwen 环境文件为 root `0600`，Qwen settings 为 `cloudagents` `0600`；进程参数不包含 token，root 临时部署文件为 0。
- Qwen `MemoryMax=768M`，worker `MemoryMax=1G`，执行单元容量为 1；验收后主机仍有约 800 MiB 可用内存。
- 失败部署产生但从未使用的 worker token 已撤销；当前 worker 使用独立的 `workers:*` 最小权限 token。

## 第二执行单元状态

香港 ECS 的公网 IP 可达，SSH 端口可以完成 TCP 建连，但 `sshd` 在服务端 banner 前超时或重置；经杭州 ECS 作为跳板复测结果一致，因此不是本地出口 IP 限制。该主机已有受保护的运行服务，本轮未擅自重启。恢复 SSH 后，应复用其已有 loopback Qwen daemon，再运行本文相同的两轮验收。

## 可重复命令

详见 `docs/remote-ecs-workers.md`。核心验收命令：

```bash
RUN_MANAGER_TOKEN=replace-with-manager-token \
python3 scripts/validate_remote_execution_units.py \
  --unit-id ecs-hz \
  --worker-id worker-ecs-hz \
  --rounds 2
```

验收成功的充分条件是脚本最后输出 `"ok": true`，且每个结果都包含目标 `unit_id`、目标 `worker_id` 和非空 `remote_run_ids`。
