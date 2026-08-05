# 本地开发：主站 → Mavis Gallery 登录桥与完整服务链

## 目标

本机跑通完整链路：

```text
主站 Flask (8100)  →  首页 AI 作图卡片  →  Gallery Web (3000)
  →  /api/me/session（服务端 introspection，凭 Flask 会话 Cookie）
  →  Generation API (3101) → PostgreSQL(5433) / Redis(6380)
  →  Dispatcher + Worker → COS
```

登录信息不共享的根因是 **浏览器在 Gallery 域名上没有主站会话 Cookie**。只有两种解决方式：

1. 本地/同域开发：Flask 与 Gallery 在同一主机（不同端口即可，Cookie 按域名不分端口），Gallery 服务端把浏览器 Cookie 转发给 Flask introspection。
2. 生产：两个站点必须位于**同一个可控父域名**（如 `mindfulpenpal.com` 与 `gallery.mindfulpenpal.com`），Flask 设置 `SESSION_COOKIE_DOMAIN=.mindfulpenpal.com` 与 `SESSION_COOKIE_SECURE=true`。`*.vercel.app` 等不可控域名无法共享 Cookie。

## 一键脚本

```powershell
# 1. 补齐缺失的环境变量（幂等，只打印变量名，不打印值）
.\scripts\dev\setup-local-env.ps1

# 2. 启动整套服务（自动检测 Redis；需要 Docker 或本机已有 Redis）
.\scripts\dev\dev-up.ps1

# 3. 健康检查（含登录桥与工作流列表）
.\scripts\dev\dev-health.ps1

# 4. 停止服务（Redis 容器保留）
.\scripts\dev\dev-down.ps1
```

`dev-up.ps1` 启动：Flask（根 `.env` 的 `PORT`，默认 8100）、Gallery Web（3000）、Generation API（3101）、Outbox Dispatcher、Generation Worker。日志在 `.tmp/dev-*.log`，PID 记录在 `.tmp/dev.pids.json`。

## 端口与冲突

本机若被其他项目占用端口（例如 Docker 里已运行其他 Redis/Postgres），脚本不会强制抢占：

| 服务 | 默认端口 | 说明 |
| --- | --- | --- |
| Flask 主站 | 8100 | 8000 被其他容器占用时可改根 `.env` 的 `PORT` |
| Gallery Web | 3000 | `apps/gallery-web/.env` 的 `GALLERY_PUBLIC_ORIGIN` 需一致 |
| Generation API | 3101 | `services/generation-service/.env` 的 `GALLERY_PORT` |
| Redis | 6380 | 避免与 6379 上其他带密码的 Redis 冲突 |
| PostgreSQL | 5433 | 使用本机 PostgreSQL 18 服务（`mavis`/`mavis-dev-local`，库 `mavis_dev`） |

`setup-local-env.ps1` 支持 `-FlaskPort / -GalleryPort / -ApiPort / -RedisPort` 和 `-RefreshUrls`（刷新所有 URL 指向新端口），`-ForceSecrets` 轮换两把开发共享密钥。

## 需要哪些环境变量

- 根 `.env`：`AI_IMAGE_EXTERNAL_URL`（指向 `/create`）、`GALLERY_INTROSPECTION_SECRET`、`GALLERY_SERVICE_BASE_URL`、`GALLERY_INTERNAL_HMAC_SECRET`、`DATABASE_URL`。
- `apps/gallery-web/.env`：`GALLERY_SERVICE_BASE_URL`、`GALLERY_INTERNAL_HMAC_SECRET`、`MAVIS_AUTH_INTROSPECTION_URL`、`GALLERY_INTROSPECTION_SECRET`、`GALLERY_PUBLIC_ORIGIN`、`MAVIS_AUTH_LOGIN_URL`、`MAVIS_AUTH_LOGOUT_URL`。
- `services/generation-service/.env`：`DATABASE_URL`、COS 五件套、`GALLERY_CURSOR_SECRET`、`GALLERY_INTERNAL_HMAC_SECRET`、`REDIS_URL` 与全部 `BULLMQ_*`/`GENERATION_*` 运行参数。

示例文件：`.env.example`、`apps/gallery-web/.env.example`、`services/generation-service/.env.example`。

Generation Service 的 npm 脚本通过 `--env-file-if-exists=.env` 自动加载本目录 `.env`；Gallery Web 由 Next.js 自动加载；Flask 由 python-dotenv 加载。

## 首次初始化本地数据库

```powershell
# 1. 建角色与库（本机 PostgreSQL 18 在 5433，管理员 postgres 免密）
psql -h 127.0.0.1 -p 5433 -U postgres -c "CREATE ROLE mavis LOGIN PASSWORD 'mavis-dev-local'; CREATE DATABASE mavis_dev OWNER mavis;"

# 2. 让 Flask 建业务表（public.users 等）
.\.venv\Scripts\python.exe -c "from app import create_app; create_app()"

# 3. 依次应用 Generation 迁移
Get-ChildItem services\generation-service\database\migrations -Filter *.sql | Sort-Object Name |
  ForEach-Object { psql "postgresql://mavis:mavis-dev-local@127.0.0.1:5433/mavis_dev" -v ON_ERROR_STOP=1 -f $_.FullName }

# 4. 本地预览启用 Mock Provider
psql "postgresql://mavis:mavis-dev-local@127.0.0.1:5433/mavis_dev" -c "UPDATE ai.providers SET status='active' WHERE code='mock';"
```

> 注意：不要把本地开发指向生产/线上数据库。线上与本地必须分开。

## 验证清单

1. 主站首页出现“AI 作图”卡片，指向 `http://127.0.0.1:<gallery-port>/create`。
2. 主站登录后，Gallery `/api/me/session` 返回 `{"role":"user|admin","bridge":"ok","userId":N}`；未登录返回 `role=guest`。
3. `/create` 可列出工作流；提交任务后 `pending → running → completed`，画廊可打开作品。
4. `dev-health.ps1` 全部 OK。

## 故障排查

| 现象 | 原因与处理 |
| --- | --- |
| Gallery 一直显示“登录” | 浏览器在 Gallery 域名没有主站 Cookie。检查 `SESSION_COOKIE_DOMAIN`/`SESSION_COOKIE_SECURE`（生产同父域）或本地端口是否同主机；再检查两把密钥是否一致 |
| `bridge=unconfigured` | `apps/gallery-web/.env` 缺少 `MAVIS_AUTH_INTROSPECTION_URL` 或 `GALLERY_INTROSPECTION_SECRET` |
| `bridge=error` | Flask introspection 不可达/返回非 JSON/密钥错误；查看 `.tmp/dev-flask.log` |
| 首页没有 AI 卡片 | `AI_IMAGE_EXTERNAL_URL` 未配置或不是 HTTPS（本地仅允许 loopback HTTP） |
| 工作流列表 503 | Generation API 未启动，或 `DATABASE_URL` 不可达 |
| 任务一直 pending | Dispatcher 未启动、Redis 不可达，或 outbox 未发布 |
| 任务 failed `internal_error` | 查看 `.tmp/dev-worker.err.log`；COS 上传失败通常是密钥无效，或元数据头含下划线（已修复为 `job-id` 形式） |
