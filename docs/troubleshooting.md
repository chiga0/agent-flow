# 排障手册

这篇按症状定位问题。排障时建议先用 fake run 判断平台主链路，再用 qwen run 判断真实执行器链路。

## 登录失败

先确认你输入的是邮箱，不是历史用户名。

当前登录规则：

- 邮箱：`RUNTIME_AUTH_EMAIL`
- 密码：优先 `RUNTIME_AUTH_PASSWORD`，没有则 fallback 到 `RUNTIME_BASIC_AUTH_PASSWORD`

如果仍失败：

1. 确认 GitHub Secrets 名字拼写正确。
2. 重新运行 `Deploy Runtime`，让 VPS 上环境文件更新。
3. 在服务器检查 `/etc/cloud-agents-runtime.env` 里是否有对应 bootstrap env。
4. 如果已经创建过历史用户，确认最新代码是否已同步并重启 runtime。

当前还没有邮箱验证码、SMTP 验证和找回密码。忘记密码时需要更新 secret 后重新部署，或由管理员在服务器侧重置本地用户数据。

## 页面能打开，但 API 提示 401

这通常说明登录 session 没有建立或已失效。

处理：

- 退出后重新登录。
- 确认浏览器访问的是同一个域名和路径前缀，例如都使用 `/cloud-agents/`。
- 如果用 curl，先调用 `/auth/login` 保存 cookie，再带 cookie 请求 API。
- worker API 不走浏览器 session，应该使用 `/cloud-agents-worker/` 和 scoped bearer token。

## Run 一直 running，没有状态更新

先看 Run Detail：

1. Agent Chat 是否仍在输出。
2. 是否出现 permission request。
3. Event Stream 最后一条 event 是什么。
4. Artifacts 是否已有 `diagnostics.json` 或 executor 日志。
5. Executors 页面是否有 active lease。

常见原因：

| 原因 | 表现 | 处理 |
| --- | --- | --- |
| 等待权限 | 有 permission bubble | 批准或拒绝 |
| worker 容量满 | queue 有积压，Units 显示满载 | 增加 worker 或降低并发 |
| worker stale | Units 心跳过旧 | 重启 worker，必要时 retry |
| qwen executor 卡住 | executor running 但无输出 | 看 stderr、资源和 qwen settings |
| VPS 资源耗尽 | Web 慢、SSH 慢、HTTP 超时 | 降低 capacity，拆分控制面和 worker |

## qwen 失败

如果 fake run 成功但 qwen 失败，平台主链路大概率正常。

按顺序检查：

1. `QWEN_SETTINGS_JSON` 是否配置到了 GitHub Secret。
2. VPS 上 qwen CLI 是否能启动。
3. executor strategy 是否符合预期，例如低配先用 `shared`。
4. Run Detail Artifacts 里的 `executor.stderr.log`。
5. 权限请求是否一直没处理。
6. VPS 内存、swap、磁盘是否不足。

qwen 验收命令：

```bash
python3 scripts/validate_qwen_mission.py \
  --base-url http://127.0.0.1:8765 \
  --token "$RUN_MANAGER_TOKEN" \
  --validate-single-run \
  --expect-executor-strategy shared \
  --timeout 600
```

## CI 部署失败

先看失败在哪一步。

| 步骤 | 常见原因 | 处理 |
| --- | --- | --- |
| Validate required secrets | secret 缺失 | 补 `RUNTIME_SSH_TARGET`、`RUNTIME_SSH_KEY`、登录密码 |
| Runtime/Web tests | 代码问题 | 本地复现测试 |
| Write deploy credentials | key 或 qwen settings 格式不对 | 私钥填完整内容，JSON 保持合法 |
| Deploy runtime to VPS | SSH 超时、VPS 卡死、防火墙 | 重启 VPS，检查 22 端口和负载 |
| Smoke test deployed runtime | 服务没起来 | 看 systemd 和 journal |
| Smoke public ingress | Nginx、域名、登录配置问题 | 检查 `/cloud-agents/`、cookie 和 env |

VPS 卡死时常见现象是：22/80/443 能建立 TCP 连接，但 SSH 不返回 banner，HTTP/HTTPS 建连后无响应。这通常是机器负载或网络栈卡住，不像单纯安全组没开。

## Runtime Monitor 失败

Monitor 会检查公网入口、登录、静态资源、健康接口和基础 JSON API。

排查顺序：

1. 访问 `https://<domain>/cloud-agents/auth/session`，未登录应返回 `login_required=true`。
2. 访问 `/cloud-agents/` 是否出现登录页。
3. 确认 `RUNTIME_PUBLIC_HOST`、`RUNTIME_PUBLIC_DOMAIN` 或 `RUNTIME_PUBLIC_URL` 配置正确。
4. 确认 monitor 使用的登录邮箱/密码和部署一致。
5. 到 VPS 上检查 `systemctl status cloud-agents-runtime` 和 Nginx。

## Worker 不认领任务

检查：

- Units 页面是否有 heartbeat。
- worker token scope 是否包含 `workers:*`。
- worker control URL 是否指向 `/cloud-agents-worker` 或正确的 control base。
- capacity 是否大于 0。
- adapter 能力是否匹配任务 adapter。
- worker 是否被 drain。

处理顺序：

1. Resume worker。
2. Retry 卡住任务。
3. 重启 worker service。
4. 必要时 revoke token 后重新注册。
