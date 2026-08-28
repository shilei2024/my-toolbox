# 腾讯云 CVM 后端部署指南

## 当前状态

目标是 Ubuntu CVM + Docker Compose。`release/0.4.0` 已补齐生产 Dockerfile、根级 `deploy/docker-compose.production.yml` 与 Generation API/Dispatcher/Worker 完整入口；本文继续作为标准与操作顺序，实际部署请以 [小白生产部署指南](../../deploy/DEPLOY_GUIDE.md) 与 [腾讯云资源准备指南](tencent-cloud-setup-guide.md) 为准。

生产发布仍需满足：CI 全绿、[上线验收清单](ai-merge-acceptance.md) 10 项通过、独立审批合入 `main`。

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

## 客户项目 Phase 1–4 更新与首次启用

客户项目是主站 Flask 模块，必须与现有站点使用同一不可变发布包。只有合并 PR、CI 全绿、staging 验证和生产发布审批全部完成后，才能把同一镜像 digest 晋级到腾讯云；不要在 CVM 上 `git pull`、临时改代码或构建。若主站 Flask 实际不运行在该 CVM，应在主站的受控 one-off job 执行下列迁移，而不是在无应用代码的 Generation Service 容器中执行。

迁移前创建 PostgreSQL 备份并保存备份 ID、当前镜像 digest 和 `flask db current` 输出。在应用目录或同镜像的一次性迁移容器中执行：

```bash
cd /opt/mindfulpenpal
export FLASK_APP='app:create_app'
export AUTO_CREATE_SCHEMA=false
flask db current
flask db heads
flask db upgrade
flask db current
```

预期 `heads` 和升级后的 `current` 都显示 revision `f7a8b9c0d1e2` 且退出码为 `0`。这条迁移链只新增组织工作日日历、导入批次、受控导出策略和保存视图表；生产事故处理中仍不得执行 downgrade。然后确认环境文件中：

```dotenv
CUSTOMER_PROJECTS_ENABLED=false
CUSTOMER_PROJECTS_PILOT_EMAILS=
CUSTOMER_PROJECT_REMINDERS_ENABLED=false
CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=false
AUTO_CREATE_SCHEMA=false
```

先以关闭开关启动并验证主站、登录、健康检查和现有工具，再执行以下 staging/试点验收：

1. 验证组织隔离、项目成员范围、乐观锁 409、生命周期重新激活和衍生关系。
2. 日历节假日/调休能移动提醒日期；通知保持 dry-run，确认发件箱幂等后才单独审批 SMTP。
3. Excel 导入先预览，确认后重复提交不重复创建；只撤销创建后未被修改的项目。
4. 受控导出默认仅管理员/业务经理，超限被拒绝，审计文件 SHA-256 与下载文件一致。
5. 个人保存视图跨用户返回 404；组织共享视图只有组织管理员能发布或删除。
6. 观察数据库、应用内存、5xx、403/404、409 和审计事件，完成备份恢复演练。

全部通过后，审批人再写入少量 `CUSTOMER_PROJECTS_PILOT_EMAILS`，开启 `CUSTOMER_PROJECTS_ENABLED=true` 并滚动重启。回滚时先关闭客户项目、提醒和通知开关，再恢复上一稳定镜像 digest；保留新增表、导入批次、策略、视图和业务记录，不执行 `flask db downgrade`。完整分阶段手册见本目录的 customer-project-tracking Phase 1–4 文档。

## 常见失败

- `manifest unknown`：digest/tag 不存在；停止，不要改用 `latest`。
- healthcheck 失败：查看目标服务安全日志，回滚到旧 digest。
- migration 失败：停止应用晋级，在恢复库定位；禁止反复执行生产 SQL。
- Redis/数据库连接失败：检查私网、安全组、TLS 和 env；禁止临时开放公网端口。
- COS 403：检查 Region、Bucket、CAM 最小权限和系统时间，不要换成主账号永久密钥。
