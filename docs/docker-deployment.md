# Docker 部署

这套部署适合在一台 Linux 服务器、本地电脑或 NAS 上运行 AgentFlow Client、控制面和一个真实 Qwen Code 执行器。默认只监听 `127.0.0.1:8765`，不会直接暴露到公网。

## 适用边界

| 机器 | 建议用途 | 并发 |
| --- | --- | --- |
| 2C2G | 个人体验、轻量任务、短时真实 Qwen 执行 | 固定为 1 |
| 4C8G 及以上 | 日常使用、中等代码库与较长任务 | 从 1 开始压测 |
| 多用户或重型构建 | 控制面和执行单元分离 | 按执行单元扩容 |

2C2G 可以运行，但不要在同一时间进行 Docker 构建、完整 CI、大仓库编译和多个 Qwen 任务。内存不足会让 Linux OOM Killer 终止 Qwen 或 runtime。生产环境优先在 CI 构建镜像，再由服务器拉取；至少保留 512 MB 给操作系统和反向代理。

## 前置条件

- Docker Engine 24+，含 Compose v2；
- 一个专门给 Agent 使用的工作目录；
- 已经可用的 Qwen Code `settings.json`，通常位于 `~/.qwen/settings.json`；
- Linux 服务器如需公网访问，应另配 Nginx/Caddy/Tailscale/Cloudflare Tunnel 和 HTTPS。

不要把整个主目录挂载给 Agent。工作目录会以读写方式挂载，Qwen 有权修改其中的文件。

## NAS 部署

支持 Docker Compose 的 NAS 可以直接运行本方案。推荐通过 SSH 在 NAS 上部署，而不是手工把两份 Compose 配置逐项录入管理界面，这样升级和审计更可靠。

部署前先确认：

```bash
uname -m
docker version
docker compose version
free -h
```

- `x86_64` 可直接使用当前已验收的镜像链路；`aarch64`/`arm64` 的基础镜像虽然是多架构镜像，但仍需在该 NAS 上重新运行 `qwen-smoke`，不能用 x86 验收结果代替；
- NAS 的工作目录和 Qwen settings 必须使用 NAS 自己的 Linux 绝对路径，例如 `/volume1/docker/agentflow/workspace`，不能沿用 macOS 路径；
- 给容器保留至少 2 GB 可用内存。2 GB 机器保持单并发，并停止同机的索引、转码等重负载任务；
- 端口默认只绑定 NAS 的 `127.0.0.1`。远程使用时优先通过 NAS 反向代理加 HTTPS，或通过 Tailscale/VPN 访问，不要直接把 8765 暴露到公网。

如果 NAS 内存较小，不建议在 NAS 上构建镜像。可以在同 CPU 架构的开发机或 CI 完成构建，再传入 NAS：

```bash
# 构建机
./scripts/docker_deploy.sh build
docker save deploy-runtime:latest | gzip > agentflow-runtime.tar.gz

# 将文件复制到 NAS 后
gzip -dc agentflow-runtime.tar.gz | docker load
./scripts/docker_deploy.sh up-no-build
./scripts/docker_deploy.sh smoke
./scripts/docker_deploy.sh qwen-smoke
```

`qwen-smoke` 会显式固定到 `local-dev` 执行单元，确保它验证的是 Docker 容器内的 Qwen，而不会在已注册远端 ECS 后被自动调度到远端 worker。

不同 CPU 架构之间不能直接复用单架构镜像。NAS 管理界面如果自动更改 Compose 项目名，artifacts 和 Qwen state 卷名也会随之变化；备份前以 `docker volume ls` 的实际结果为准。

## 首次部署

在仓库根目录执行：

```bash
python3 scripts/init_docker_env.py \
  --workspace /absolute/path/to/workspace \
  --qwen-settings /absolute/path/to/.qwen/settings.json \
  --email owner@example.com

./scripts/docker_deploy.sh up
./scripts/docker_deploy.sh smoke
./scripts/docker_deploy.sh qwen-smoke
```

初始化脚本会生成 `.env.docker`，自动创建随机 token、登录密码和 session secret，并将权限设为 `0600`。文件已被 Git 和 Docker 构建上下文忽略。

访问地址：

```text
http://127.0.0.1:8765/#/
```

查看本机登录账号和密码：

```bash
awk -F= '$1 == "RUN_MANAGER_BOOTSTRAP_EMAIL" || $1 == "RUNTIME_BOOTSTRAP_PASSWORD" { print }' .env.docker
```

不要把该命令输出贴到工单、聊天或 CI 日志中。首次登录后，可在管理后台创建独立用户。

## 日常操作

```bash
./scripts/docker_deploy.sh status
./scripts/docker_deploy.sh logs
./scripts/docker_deploy.sh smoke
./scripts/docker_deploy.sh qwen-smoke
./scripts/docker_deploy.sh up-no-build  # 已预载镜像时使用
./scripts/docker_deploy.sh down
```

`smoke` 验证登录、任务、事件和结果链路；`qwen-smoke` 会创建一个只读任务，并且只有结果明确来自 `real-cli` 才算通过。两个 smoke 每次都会创建新任务，避免旧的幂等结果掩盖故障。

## 2C2G 默认保护

`deploy/runtime.2c2g-qwen.env.example` 已设置：

- runtime 容器上限为 1.75 CPU、1536 MB 内存、512 PIDs；
- worker capacity 为 1；
- 单任务最大申报资源为 1.5 CPU、1400 MB；
- Qwen Code 固定为经过验收的 `0.19.11`；
- `auto` 在真实 Qwen 可用时选择 Qwen，否则安全退回 fake；
- 根文件系统只读、移除 Linux capabilities，并启用 `no-new-privileges`；
- 使用容器 init 回收 Qwen 子进程，并将容器日志限制为 3 个 10 MB 文件；
- Qwen settings 只读挂载，工作目录读写挂载；
- Git 的 ownership 例外只作用于明确挂载的 `/workspace`，确保 NAS/macOS bind mount 仍可执行代码审计；
- CLI 子进程会关闭嵌套的真实适配器，Agent 即使运行项目测试也不会递归拉起更多 Qwen；
- 端口只绑定到 localhost。

如果系统频繁 swap、Qwen 被退出或容器出现 `OOMKilled=true`，不要提高并发。先将机器升级到 4C8G，或把 Qwen worker 移到另一台机器。

## 公网接入

容器默认只监听宿主机回环地址。推荐让反向代理转发到 `http://127.0.0.1:8765`，并满足：

- 只开放 443，强制 HTTPS；
- 保留登录 Cookie、SSE 和长请求；
- 限制管理端来源，或放在 VPN/Zero Trust 后；
- 不把 `.env.docker`、Qwen settings 或工作目录作为静态文件发布；
- 为宿主机、防火墙和 Docker 持续安装安全更新。

## 升级、备份与恢复

升级前先备份命名卷：

```bash
docker run --rm \
  -v deploy_runtime-artifacts:/data:ro \
  -v "$PWD":/backup \
  alpine:3.20 \
  tar czf /backup/agentflow-artifacts.tgz -C /data .
```

然后更新代码并重新部署：

```bash
git pull --ff-only
./scripts/docker_deploy.sh up
./scripts/docker_deploy.sh smoke
./scripts/docker_deploy.sh qwen-smoke
```

恢复时先停止容器，将备份解压回同一个 artifacts 卷，再启动并运行 smoke。`.env.docker` 和 Qwen settings 必须单独放入受控的加密备份；命名卷备份不包含它们。

## 验收清单

部署只有同时满足以下条件才算可用：

1. `status` 显示容器为 `healthy`；
2. fake smoke 完成；
3. qwen smoke 完成且执行模式为 `real-cli`；
4. Web 登录、新建会话、会话列表可用；
5. 390px 宽度下新建会话和移动决策台无横向滚动；
6. `docker inspect` 显示资源限制、只读根文件系统和安全选项生效；
7. 重启容器后历史会话仍存在。

## 常见问题

### Qwen 参数不识别

确认镜像中的版本：

```bash
docker exec deploy-runtime-1 qwen --version
```

本方案固定为 0.19.11。修改 `QWEN_NODE_PACKAGE` 或 `V2_QWEN_CODE_COMMAND` 后必须重建镜像并重新运行 qwen smoke。

### 基础镜像拉取失败

示例默认使用 AWS Public ECR，避免部分 Docker Hub 镜像代理问题。若所在网络无法访问，可在 `.env.docker` 中将 `NODE_IMAGE` 和 `PYTHON_IMAGE` 改为组织内已审计的镜像仓库地址，然后重建。

### 真实任务退回 fake

检查容器中的 Qwen 是否存在、`V2_ENABLE_REAL_CLI_ADAPTERS=1` 是否生效，以及 Qwen settings 是否可读。`auto` 只有在可执行文件和真实适配器开关都有效时才选择 Qwen。
