# 腾讯云 CVM 后端部署指南

## 当前状态

目标是 Ubuntu CVM + Docker Compose，但仓库目前没有生产 Dockerfile、production Compose 和 Generation API/Dispatcher/Worker 完整入口。因此本文定义标准和操作顺序，**当前不得按文档直接部署生产**。这些阻断项关闭后，才能启用后端 CD。

## 设计

- CI 构建不可变镜像，CVM 只 `pull`，不在生产服务器编译源码。
- staging 和 production 使用同一镜像 digest。
- Compose 文件进入 Git；真实 env 文件只在服务器或 Secret Manager。
- PostgreSQL、Redis、COS 使用独立托管资源和私网。
- Nginx/负载均衡器只暴露批准的 443 路由。

腾讯云 CVM 官方文档支持在 Ubuntu 安装 Docker Engine、Buildx 和 Compose plugin。[腾讯云 CVM Docker 指南](https://intl.cloud.tencent.com/document/product/213/37516)

## 服务器首次准备

管理员执行：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl postgresql-client
docker --version
docker compose version
```

预期输出包含 Docker 与 Compose 版本。若命令不存在，按腾讯云官方 Docker 安装文档完成；不要从非官方脚本下载 root 安装器。

创建受限目录：

```bash
sudo install -d -m 0750 -o root -g docker /opt/mindfulpenpal
sudo install -d -m 0750 -o root -g docker /opt/mindfulpenpal/releases
sudo install -d -m 0750 -o root -g docker /opt/mindfulpenpal/backups
sudo install -m 0600 -o root -g root /dev/null /etc/mindfulpenpal.production.env
```

预期：env 文件只有 root 可读。部署用户只能执行受限部署脚本和读取镜像，不应拥有数据库超级用户、COS 全桶管理或任意 sudo。

## 计划中的 Compose 约束

生产 Compose 必须：

- 使用 `image: repository@sha256:digest`，禁止 `build:`。
- 为每个 HTTP 服务定义 healthcheck。
- 设置 restart policy、资源限制、只读文件系统/临时目录（可行时）。
- 不把 PostgreSQL、Redis、ComfyUI 端口映射到公网。
- 通过 `env_file` 注入 `/etc/mindfulpenpal.production.env`。
- 数据库 migration 作为一次性受控 job，不在每个副本启动时并发运行。

## staging 部署流程

```bash
cd /opt/mindfulpenpal
export RELEASE_IMAGE='ghcr.io/shilei2024/my-toolbox@sha256:<digest>'
docker compose --env-file /etc/mindfulpenpal.staging.env \
  -f compose.yaml -f compose.staging.yaml config --quiet
docker compose --env-file /etc/mindfulpenpal.staging.env \
  -f compose.yaml -f compose.staging.yaml pull
```

预期：配置检查无输出并返回 `0`；pull 显示目标 digest 下载完成。接着备份和 dry-run migration，再执行：

```bash
docker compose --env-file /etc/mindfulpenpal.staging.env \
  -f compose.yaml -f compose.staging.yaml up -d --no-build --remove-orphans
docker compose -f compose.yaml -f compose.staging.yaml ps
```

预期：服务为 `running/healthy`。执行 smoke、队列、COS、支付 Test Mode 和回滚演练。

## production 部署流程

1. 完成[发布检查清单](../operations/release-checklist.md)。
2. GitHub `production` Environment 由非发起人批准。
3. 记录数据库备份 ID 和当前镜像 digest。
4. 只替换为已在 staging 验证的 digest。
5. `docker compose config --quiet`。
6. 执行一次性 migration job。
7. `docker compose up -d --no-build`。
8. 内网 health、外网 smoke、日志与指标通过后结束发布。

生产命令与 staging 相同，只将 env/override 文件替换为 production。命令模板中的文件在仓库实际补齐前不可执行。

## 常见失败

- `manifest unknown`：digest/tag 不存在；停止，不要改用 `latest`。
- healthcheck 失败：查看目标服务安全日志，回滚到旧 digest。
- migration 失败：停止应用晋级，在恢复库定位；禁止反复执行生产 SQL。
- Redis/数据库连接失败：检查私网、安全组、TLS 和 env；禁止临时开放公网端口。
- COS 403：检查 Region、Bucket、CAM 最小权限和系统时间，不要换成主账号永久密钥。
