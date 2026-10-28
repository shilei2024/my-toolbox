# M1 Generation Staging 服务器部署

## 目标与限制

本手册把 Generation API、Dispatcher、Worker、PostgreSQL、Redis 和 Caddy 部署到一台仅用于预发布验证的 Linux 服务器。Vercel 只运行 `apps/gallery-web`。PostgreSQL、Redis、COS 凭据和 Provider 凭据不得暴露给浏览器或直接开放到公网。

4 CPU / 4 GB 内存足够运行低并发 Mock 或远程 Provider 验证，但不适合本机运行 ComfyUI/GPU，也不应作为正式生产数据库与队列的单点。正式生产应迁移到独立高可用 PostgreSQL、Redis 和可扩展 Worker。

## 1. 发布前检查

1. 为 API 准备独立测试域名，例如 `api-ai-staging.example.com`，添加 A 记录指向服务器。
2. 安全组只允许管理来源访问 SSH；公网仅开放 TCP 80 和 443。
3. 不开放 3101、5432、6379。它们只存在于 Docker 内部网络。
4. COS 使用独立 Staging bucket，或使用限制到独立 Staging prefix 的最小权限子账号。
5. 确认至少预留 15 GB 磁盘空间，并启用云硬盘快照或外部备份。

成功标准：域名解析到服务器；`docker version` 与 `docker compose version` 均成功；80/443 没有被未知进程占用。

## 2. 获取可审计源码

```bash
git clone https://github.com/shilei2024/my-toolbox.git
cd my-toolbox
git fetch origin
git checkout codex/m1-generation-api
git rev-parse --short HEAD
```

预期提交必须经过本地测试并与待验证的 Vercel Preview 使用同一功能分支。不要在服务器直接修改源码。

## 3. 创建 Staging 环境文件

```bash
cd services/generation-service
cp deploy/.env.staging.example deploy/.env.staging
chmod 600 deploy/.env.staging
```

分别生成数据库、Redis 和三个签名密钥，不复用 Flask `SECRET_KEY`：

```bash
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

编辑 `deploy/.env.staging`：

- 设置真实 `GENERATION_API_DOMAIN`。
- 设置不同的 `POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`GALLERY_CURSOR_SECRET`、`GALLERY_INTERNAL_HMAC_SECRET`。
- 从安全来源写入 `COS_SECRET_ID`、`COS_SECRET_KEY`、`COS_BUCKET`、`COS_REGION`。
- `GALLERY_ASSET_HOSTS` 只填写真实 COS/CDN hostname，不带协议、路径或通配符。
- 初次测试保持 `APP_ENV=staging`、`GENERATION_ALLOW_MOCK_PROVIDER=true`、`BULLMQ_CONCURRENCY=1`。
- 不启用 Stripe，不填写不使用的 Provider API Key。

禁止把填好值的文件提交到 Git；仓库 `.gitignore` 已忽略 `.env.staging`。

## 4. 验证 Compose 并首次启动

所有命令均从 `services/generation-service` 执行：

```bash
docker compose --env-file deploy/.env.staging \
  -f deploy/compose.staging.yaml config --quiet

docker compose --env-file deploy/.env.staging \
  -f deploy/compose.staging.yaml build

docker compose --env-file deploy/.env.staging \
  -f deploy/compose.staging.yaml up -d
```

`migrate` 使用 `public.schema_migrations` 记录已应用文件，重复启动不会再次执行旧迁移。首次启动预期依次通过 PostgreSQL、Redis、迁移、API 健康检查，随后启动 Dispatcher、Worker 和 Caddy。

```bash
docker compose --env-file deploy/.env.staging \
  -f deploy/compose.staging.yaml ps

docker compose --env-file deploy/.env.staging \
  -f deploy/compose.staging.yaml logs --tail=100 api dispatcher worker caddy
```

成功日志包含 `gallery.api_started`、`queue.dispatcher_started`、`queue.generation_worker_started`，并且 Caddy 成功取得域名证书。

```bash
curl --fail --show-error https://api-ai-staging.example.com/health
```

预期响应：`{"status":"ok"}`。

## 5. 仅在 Staging 启用 Mock

迁移会创建 Mock Provider，但默认禁用。确认当前连接的是 `generation_staging` 数据库后执行：

```bash
docker compose --env-file deploy/.env.staging \
  -f deploy/compose.staging.yaml exec -T postgres \
  sh -ec 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "UPDATE ai.providers SET status = '\''active'\'' WHERE code = '\''mock'\'' AND adapter_type = '\''mock'\'';"'
```

生产环境禁止启用 Mock；Worker 还会在 `APP_ENV=production` 时拒绝启动 Mock。

## 6. 配置 Vercel Preview

在 `my-toolbox-gallery` 项目的 Preview 环境设置：

- `GALLERY_SERVICE_BASE_URL=https://<Generation Staging API domain>`
- `GALLERY_INTERNAL_HMAC_SECRET=<与 Generation Service 完全相同>`
- `GALLERY_PUBLIC_ORIGIN=https://<固定 Preview branch alias>`
- `MAVIS_AUTH_LOGIN_URL=https://<Staging Flask>/login`
- `MAVIS_AUTH_LOGOUT_URL=https://<Staging Flask>/logout`

重新部署 Preview 后验证 `/api/generation/workflows`。共享登录还需要：

- `MAVIS_AUTH_INTROSPECTION_URL=https://<Staging Flask>/internal/gallery/session`
- `GALLERY_INTROSPECTION_SECRET=<与 Staging Flask 相同的独立密钥>`

普通 `vercel.app` 域名不能共享业务父域 Cookie。完整登录验证必须给 Flask 和 Gallery 配置受控的同父域 Staging 子域，并设置安全 Cookie Domain。

Staging 环境模板新增（可选）：

- `BILLING_SIGNUP_GRANT=10`：新用户首次汇总时发放的一次性积分。
- `GALLERY_DEFAULT_MODERATION=pending`：`approved` 仅用于快速验收公开画廊链路。

数据库迁移按编号应用到 `0007_remote_provider_bindings.sql`；`0007` 只为远端 Provider 增加 bindings，Provider 行仍默认 disabled。

## 7. 备份、恢复与容量检查

首次生成任务前和每次迁移前创建备份：

```bash
sh deploy/backup-staging.sh
ls -lh deploy/backups
```

备份文件必须复制到服务器外或云对象存储。恢复到新空库：

```bash
docker compose --env-file deploy/.env.staging \
  -f deploy/compose.staging.yaml exec -T postgres \
  sh -ec 'pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < deploy/backups/<backup-file>.dump
```

定期执行 `docker stats --no-stream`、`df -h` 和 `docker system df`。不要使用 `docker system prune --volumes`，它可能删除数据库或 Redis 数据卷。

## 8. 回滚

先暂停新任务，再优雅关闭 Worker：

```bash
docker compose --env-file deploy/.env.staging \
  -f deploy/compose.staging.yaml stop dispatcher

docker compose --env-file deploy/.env.staging \
  -f deploy/compose.staging.yaml stop -t 45 worker api caddy
```

随后从 Vercel Preview 移除 `GALLERY_SERVICE_BASE_URL` 或回滚到上一部署。保留 PostgreSQL、Redis、Caddy 数据卷，不执行 `down -v`。需要恢复时切回已验证提交，重新 `build` 和 `up -d`。

## 9. 常见失败

- Caddy 无法签发证书：检查 DNS、生效时间、80/443 和安全组。
- API 不健康：检查迁移日志、数据库连接、COS hostname 与 32+ byte secret。
- Worker 退出：检查全部 BullMQ 数值变量、COS 配置、临时目录和 Provider 配置。
- Workflow 为空：确认 `0007` 已应用，并只在 Staging 启用 Mock 或真实 Provider。
- 一直 pending：检查 Dispatcher、Redis 和 outbox 日志。
- Vercel 返回 503：确认 Preview 环境变量已保存并重新部署。
