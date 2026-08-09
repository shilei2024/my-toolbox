# 已有服务器与 COS 的生产部署（数据库搬迁版）

> 适用条件：你**已经**有一台腾讯云服务器（已装 Docker、Docker Compose、PostgreSQL），
> 已经创建好 COS 桶，并且决定把原站数据库搬到这台服务器上。
> 从零购买资源的完整教程请看 [腾讯云资源准备指南](tencent-cloud-setup-guide.md)。

## 0. 最终长什么样

```text
用户浏览器
  ├─ mindfulpenpal.com        → Vercel 上的原网站（Flask：登录/注册/工具）
  │     └─ 首页“AI 作图”卡片 → 跳到 gallery.mindfulpenpal.com/create
  └─ gallery.mindfulpenpal.com → Vercel 上的 Gallery Web（Next.js BFF）
                                   │
                                   │ 内部调用（HMAC 签名）
                                   ▼
                          腾讯云服务器（Docker）
                            ├─ api（Generation API，3101）
                            ├─ dispatcher（数据库任务 → 队列）
                            ├─ worker（调用 AI Provider、上传 COS）
                            ├─ deletion-worker（延迟清理 COS）
                            ├─ caddy（HTTPS 反代 api-ai.mindfulpenpal.com）
                            └─ redis（容器内网队列，不暴露公网）
                          本机已装 PostgreSQL（原站数据 + ai schema）
                          腾讯云 COS（图片）
```

## 1. 开始前确认清单

| 项目 | 你的值（示例） | 说明 |
| --- | --- | --- |
| 服务器公网 IP | `<服务器公网IP>` | 登录和 DNS 都要用 |
| 服务器系统 | Ubuntu 22.04/24.04 | 已装 Docker/Compose/PostgreSQL |
| 域名 DNS 托管 | Namecheap（registrar-servers.com） | 子域名解析在 Namecheap 控制台加 |
| 后端域名 | `api-ai.mindfulpenpal.com` | A 记录 → 服务器 IP |
| 前端域名 | `gallery.mindfulpenpal.com` | CNAME → Vercel（`cname.vercel-dns.com`） |
| COS 桶名 / 地域 | 例如 `mindfulpenpal-images` / `ap-shanghai` | 已创建 |
| COS 密钥 | CAM 子账号 SecretId/SecretKey | 不要用主账号密钥 |
| 原站数据库 | Vercel Postgres / Neon / 腾讯云 PG | 必须是 PostgreSQL |
| AI Provider | 至少一个真实密钥（OpenAI/Gemini/即梦） | 没有就先准备 |

> 安全提醒：本文所有命令里的密码、连接串、密钥**只在服务器上使用**，
> 不要贴回聊天、工单，也不要提交到 Git。

## 2. 第 1 步：登录服务器并检查环境

Windows 打开 PowerShell，执行：

```powershell
ssh root@<服务器公网IP>
```

登录后逐条检查：

```bash
docker version
docker compose version
psql --version
systemctl status postgresql --no-pager | head -5
```

预期：三条命令都有版本号，PostgreSQL 状态为 `active (running)`。

检查/放行安全组（腾讯云控制台 → 云服务器 → 安全组 → 修改规则）：

| 协议/端口 | 来源 | 用途 |
| --- | --- | --- |
| TCP 22 | 你的办公 IP | SSH |
| TCP 80 | 0.0.0.0/0 | Caddy 申请 HTTPS 证书 |
| TCP 443 | 0.0.0.0/0 | HTTPS 访问 |
| TCP 5432 | 0.0.0.0/0 | Vercel 访问数据库（配合强密码 + SSL，见第 3 步） |

如果服务器开了防火墙（Ubuntu 的 ufw）：

```bash
sudo ufw status
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 5432/tcp
```

## 3. 第 2 步：配置本机 PostgreSQL（允许 Vercel 远程访问）

### 3.1 创建专用账号和数据库

不要直接用 `postgres` 超级用户跑应用。执行：

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE mavis LOGIN PASSWORD '<设置一个强密码>';
CREATE DATABASE mindfulpenpal OWNER mavis;
SQL
```

预期输出两行 `CREATE ROLE` 和 `CREATE DATABASE`。

### 3.2 开启远程监听和 SSL

先找到配置文件位置：

```bash
sudo -u postgres psql -c "SHOW config_file;"
sudo -u postgres psql -c "SHOW hba_file;"
```

编辑 `postgresql.conf`（路径以上一条命令输出为准）：

```bash
sudo nano /etc/postgresql/16/main/postgresql.conf
```

找到并改成：

```ini
listen_addresses = '*'
password_encryption = scram-sha-256
ssl = on
ssl_cert_file = '/etc/ssl/certs/server.crt'
ssl_key_file = '/etc/ssl/private/server.key'
```

生成自签证书（不需要花钱买数据库证书，`sslmode=require` 只加密不校验域名）：

```bash
sudo openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
  -keyout /etc/ssl/private/server.key -out /etc/ssl/certs/server.crt \
  -subj "/CN=<服务器公网IP>" \
  -addext "subjectAltName=IP:<服务器公网IP>,DNS:api-ai.mindfulpenpal.com"
sudo chmod 600 /etc/ssl/private/server.key
```

编辑 `pg_hba.conf`，在文件末尾加一行（`mavis` 账号从任何地方必须走 SSL）：

```ini
hostssl all mavis 0.0.0.0/0 scram-sha-256
```

重启并测试：

```bash
sudo systemctl restart postgresql
psql "postgresql://mavis:<密码>@127.0.0.1:5432/mindfulpenpal?sslmode=require" -c "SELECT 1;"
```

预期输出 `1`。报 `no pg_hba.conf entry` 说明第 3.2 的 `hostssl` 行没生效；
报 `SSL error` 说明证书路径/权限不对。

## 4. 第 3 步：把原站数据库搬迁过来

> 前提：原站是 PostgreSQL（Vercel Postgres、Neon、腾讯云 PG 等）。
> 如果是 SQLite，先停下来联系我们，流程不同。

1. 登录 Vercel → 原网站项目 → Storage → 你的 Postgres → 复制
   `POSTGRES_URL_NON_POOLING`（里面含用户名密码，只贴在服务器命令行里）。
2. 在服务器上执行（命令本身会包含原库连接串，执行完不要贴回聊天）：

```bash
pg_dump --no-owner --no-privileges "<原库连接串>" | \
  psql "postgresql://mavis:<密码>@127.0.0.1:5432/mindfulpenpal?sslmode=require"
```

3. 验证表和数据：

```bash
psql "postgresql://mavis:<密码>@127.0.0.1:5432/mindfulpenpal" -c "\dt public.*"
psql "postgresql://mavis:<密码>@127.0.0.1:5432/mindfulpenpal" -c "SELECT count(*) FROM public.users;"
```

预期能看到 `users`、`tools` 等原站表，用户数与原站一致。

4. 立即做一次备份（以后每一步出问题都能回退）：

```bash
sudo mkdir -p /opt/mindfulpenpal
pg_dump --no-owner --no-privileges \
  "postgresql://mavis:<密码>@127.0.0.1:5432/mindfulpenpal" \
  > /opt/mindfulpenpal/backup-before-ai-$(date +%F).sql
```

## 5. 第 4 步：获取代码、填写环境文件、构建镜像

```bash
sudo chown $USER /opt/mindfulpenpal
cd /opt/mindfulpenpal
git clone https://github.com/shilei2024/my-toolbox.git .
git checkout release/0.4.0
```

如果目录已存在，则：

```bash
cd /opt/mindfulpenpal
git fetch origin
git checkout release/0.4.0
git pull --ff-only origin release/0.4.0
```

创建环境文件（权限必须 600）：

```bash
sudo install -o root -g root -m 600 /dev/null /etc/mindfulpenpal.production.env
sudo cp deploy/.env.production.example /etc/mindfulpenpal.production.env
sudo chmod 600 /etc/mindfulpenpal.production.env
sudo nano /etc/mindfulpenpal.production.env
```

重点填写项：

| 变量 | 填什么 |
| --- | --- |
| `APP_ENV` | `production` |
| `PRODUCTION_RELEASE_APPROVED` | 先 `false`，预检前改 `true`（见第 7 步） |
| `GENERATION_IMAGE` | `mindfulpenpal/generation-service:0.4.0`（本机构建） |
| `POSTGRES_MIGRATION_IMAGE` | `postgres:16-alpine` |
| `CADDY_IMAGE` | `caddy:2.10-alpine` |
| `ALLOW_LOCAL_IMAGE_TAGS` | `true`（本机构建镜像时使用；有镜像仓库建议用 digest 并保持 `false`） |
| `GENERATION_API_DOMAIN` | `api-ai.mindfulpenpal.com` |
| `DATABASE_URL` | `postgresql://mavis:<密码>@host.docker.internal:5432/mindfulpenpal?uselibpqcompat=true&sslmode=require` |
| `REDIS_URL` | `redis://redis:6379`（compose 内网 Redis） |
| `ALLOW_PLAINTEXT_REDIS` | `true`（Redis 只在 Docker 内网，不发布公网端口） |
| `GALLERY_CURSOR_SECRET` / `GALLERY_INTERNAL_HMAC_SECRET` | 各自独立随机值：`openssl rand -hex 32` |
| `GALLERY_ASSET_HOSTS` | `<桶名>.cos.<地域>.myqcloud.com`（方案 B，见第 8 步） |
| `COS_SECRET_ID` / `COS_SECRET_KEY` | CAM 子账号密钥 |
| `COS_BUCKET` / `COS_REGION` | 桶名 / 地域代码（如 `ap-shanghai`） |
| `COS_CDN_BASE_URL` | 留空（方案 B 直接用 COS 域名） |
| `BILLING_PUBLIC_BASE_URL` | `https://mindfulpenpal.com` |
| `BILLING_SIGNUP_GRANT` | `10`（新用户送积分） |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` / `JIMENG_API_KEY` | 至少填一个真实密钥，对应 `*_BASE_URL` 保持默认 |

> 注意：`GALLERY_INTROSPECTION_SECRET` 不属于服务器环境文件，它是 Vercel 主站（Flask）与
> Gallery Web 两个项目之间共享的独立密钥（至少 32 字节）。Generation Service 不使用它，
> 服务器上这一项留空不会影响任何功能；必须配置在 Vercel 的两个项目里且两边完全一致。

> 注意：本地 PostgreSQL 使用自签名证书，Generation Service 的 Node `pg` 驱动默认把
> `sslmode=require` 当作 `verify-full`，会导致 worker 启动时报 `self-signed certificate`
> 崩溃。必须在连接串里加 `uselibpqcompat=true&`（node pg 兼容 libpq 语义：加密但不校验
> 证书）。主站 Flask（psycopg2）连 `127.0.0.1` 时不需要这个参数。

生成随机值的命令：

```bash
openssl rand -hex 32
```

构建镜像（国内服务器用 npmmirror 加速 npm 依赖）：

```bash
cd /opt/mindfulpenpal
docker build --build-arg NPM_REGISTRY=https://registry.npmmirror.com \
  -t mindfulpenpal/generation-service:0.4.0 services/generation-service
```

拉取另外两个镜像：

```bash
docker pull postgres:16-alpine
docker pull caddy:2.10-alpine
```

## 6. 第 5 步：执行 AI 数据库迁移（0001–0007）

用服务器本机 psql 直接执行（不需要容器）：

```bash
cd /opt/mindfulpenpal/services/generation-service
export APP_ENV=production
export DATABASE_URL="postgresql://mavis:<密码>@127.0.0.1:5432/mindfulpenpal?sslmode=require"
MIGRATIONS_DIR=database/migrations sh deploy/migrate-production.sh
```

预期输出 7 行 `applying migration: 0001_initial.sql` … `0007_remote_provider_bindings.sql`；
再次执行会显示 `migration already applied`。

验证：

```bash
psql "$DATABASE_URL" -c "\dn"
psql "$DATABASE_URL" -c "\dt ai.*"
```

预期看到 `ai` schema 和 `providers`、`generation_jobs`、`images`、`credit_accounts` 等表。

## 7. 第 6 步：预检并启动后端

把环境文件里的 `PRODUCTION_RELEASE_APPROVED=false` 改成 `true`（这表示你本人已确认发布），保存。

```bash
cd /opt/mindfulpenpal
sh services/generation-service/deploy/preflight-production.sh /etc/mindfulpenpal.production.env
```

预期输出：`production preflight passed; no secret values were printed`。

先启动内网 Redis，再启动后端：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile local-infra up -d redis

docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile production up -d --no-build
```

查看状态：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml ps
```

预期 `api` 为 `healthy`，`dispatcher`/`worker`/`deletion-worker`/`caddy`/`redis` 为 `running`。

> 注意：不要启动 compose 里的 `postgres` 服务。数据库用的是服务器本机已装的 PostgreSQL。

健康检查（需要 DNS 已生效、80/443 已放行，Caddy 首次会自动申请证书，等 1–2 分钟）：

```bash
curl https://api-ai.mindfulpenpal.com/health
```

预期：`{"status":"ok"}`。

## 8. 第 7 步：COS 图片访问（省钱方案 B）

桶是私有的，但公开画廊图片需要能被浏览器读取。采用“只放行图片目录”的桶策略：

腾讯云控制台 → 对象存储 COS → 你的桶 → 权限管理 → 存储桶策略 → 添加：

```json
{
  "Statement": [
    {
      "Action": ["cos:GetObject"],
      "Effect": "Allow",
      "Principal": { "qcs": ["*"] },
      "Resource": ["qcs::cos:<地域>:uid/<账号ID>:<桶名>/images/*"]
    }
  ],
  "Version": "2.0"
}
```

把 `<地域>`、`<账号ID>`、`<桶名>` 换成真实值。这个策略只影响 `images/jobs/*`，
私有图片仍然只能通过服务端签名 URL 访问。

> 填值规则（最容易出错的地方）：
> - `<地域>` = 桶所在地域代码，如 `ap-shanghai`；
> - `<账号ID>` = **APPID（12 位数字）**，不是登录账号也不是昵称；
> - `<桶名>` = **带 APPID 后缀的完整桶名**，例如桶显示为 `mavis-gallery-1393621694` 时，
>   Resource 应写成 `qcs::cos:ap-shanghai:uid/1393621694:mavis-gallery-1393621694/images/*`。
> 若控制台粘贴 JSON 报错，优先检查这三个值是否还留着 `<>` 尖括号占位符。

确认环境文件里已填：

```ini
COS_SECRET_ID=...
COS_SECRET_KEY=...
COS_BUCKET=<桶名>
COS_REGION=<地域代码>
COS_CDN_BASE_URL=
GALLERY_ASSET_HOSTS=<桶名>.cos.<地域>.myqcloud.com
```

改过环境文件后重新生效：

```bash
cd /opt/mindfulpenpal
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile production up -d --no-build
```

以后图片量大了，再升级成“CDN + 回源鉴权”方案（`COS_CDN_BASE_URL=https://img.你的域名`），
这里先省钱。

## 9. 第 8 步：域名 DNS（Namecheap）

你的域名 NS 是 `registrar-servers.com`（Namecheap 免费 DNS），所以在 Namecheap 控制台加记录：

1. 登录 Namecheap → Domain List → 找到 mindfulpenpal.com → Manage → Advanced DNS。
2. 先到 Vercel 的 Gallery Web 项目（Settings → Domains）添加
   `gallery.mindfulpenpal.com`，记下 Vercel 给的 CNAME 目标（通常是 `cname.vercel-dns.com`）。
3. 回到 Namecheap 添加两条记录：

| Type | Host | Value |
| --- | --- | --- |
| A Record | `api-ai` | `<服务器公网IP>` |
| CNAME Record | `gallery` | `cname.vercel-dns.com` |

验证（在本地 PowerShell）：

```powershell
Resolve-DnsName api-ai.mindfulpenpal.com
Resolve-DnsName gallery.mindfulpenpal.com
```

`api-ai` 应返回服务器 IP；`gallery` 应返回 Vercel 地址。DNS 生效一般几分钟到 1 小时。

## 10. 第 9 步：切换 Vercel 到新数据库并配置 Gallery

### 10.1 原网站项目（mindfulpenpal.com）

Vercel 项目 Settings → Environment Variables → Production：

1. **删除** `POSTGRES_URL_NON_POOLING` 和 `POSTGRES_URL`（否则它们优先级高于 `DATABASE_URL`，会继续连旧库）。
2. 新增：

| 变量 | 值 |
| --- | --- |
| `DATABASE_URL` | `postgresql://mavis:<密码>@<服务器公网IP>:5432/mindfulpenpal?sslmode=require` |
| `GALLERY_INTROSPECTION_SECRET` | 与 my-toolbox-gallery 完全一致（Vercel 两个项目共享；服务器环境文件不需要此项） |
| `SESSION_COOKIE_DOMAIN` | `.mindfulpenpal.com`（注意开头点） |
| `SESSION_COOKIE_SECURE` | `true` |
| `AI_IMAGE_EXTERNAL_URL` | `https://gallery.mindfulpenpal.com/create` |

保存后 Vercel 会自动重新部署。**立刻**打开 mindfulpenpal.com 验证：首页 200、登录正常。

> 风险提示：`SESSION_COOKIE_DOMAIN` 配错会让整站登录失效。确认登录正常再继续。

### 10.2 Gallery Web 项目（apps/gallery-web）

Vercel 项目 Settings → Environment Variables → Production 新增：

| 变量 | 值 |
| --- | --- |
| `GALLERY_SERVICE_BASE_URL` | `https://api-ai.mindfulpenpal.com` |
| `GALLERY_INTERNAL_HMAC_SECRET` | 与服务器一致 |
| `MAVIS_AUTH_INTROSPECTION_URL` | `https://mindfulpenpal.com/internal/gallery/session` |
| `GALLERY_INTROSPECTION_SECRET` | 与 Flask 一致 |
| `GALLERY_PUBLIC_ORIGIN` | `https://gallery.mindfulpenpal.com` |
| `MAVIS_AUTH_LOGIN_URL` | `https://mindfulpenpal.com/login` |
| `MAVIS_AUTH_LOGOUT_URL` | `https://mindfulpenpal.com/logout` |

确认该项目 Root Directory 为 `apps/gallery-web`，Production Branch 为 `main`。

> Vercel 新版界面入口：Project → Settings → Environments → 找到 **Production** 区块 →
> 在 “Git Branch” 选择 `main` 并保存（旧版在 Settings → Git 的 “Production Branch” 输入框，
> 新版已迁移到 Environments）。若界面没有下拉框，说明该区域已改用部署管理：
> 到 Deployments 页找到来自 `main` 的最新部署，点 “Promote to Production” 同样可让生产跟随 main。

Gallery Web 始终部署在 Vercel，不在本服务器运行；`gallery.mindfulpenpal.com` 的 DNS
保持 CNAME → `cname.vercel-dns.com`。

## 11. 第 10 步：启用 AI Provider 与验收

1. 浏览器打开原站 `/admin`，进入运营控制台（Gallery Web 的 `/admin`）。
2. 找到已配置密钥的 Provider（如 `openai`），状态从 `disabled` 改为 `active`。
3. 打开 `https://gallery.mindfulpenpal.com/create`，新用户首次进入会获得
   `BILLING_SIGNUP_GRANT` 赠送积分。
4. 按 [上线验收清单](ai-merge-acceptance.md) 逐项验收 10 项，全部通过并留档。
5. 验收通过后，按 [合并 Runbook](../operations/ai-merge-runbook.md) 把
   `release/0.4.0` 合入 `main` 并打 tag（合入前 Vercel Production Branch 仍是 `main`，
   合入会自动触发生产构建，需提前确认原站已切到新库且登录正常）。

## 12. 回滚要点

| 层面 | 怎么做 |
| --- | --- |
| 原网站 | Vercel Deployments → 回滚到上一个健康 deployment；恢复 `POSTGRES_URL_NON_POOLING` 旧值 |
| 后端 | `docker compose ... stop dispatcher worker api caddy`，恢复旧镜像 digest 后 `up -d --no-build` |
| 数据库 | 迁移只新增 `ai` schema，不删旧数据；恢复用 `/opt/mindfulpenpal/backup-before-ai-*.sql` |
| 代码 | `main` 回滚到 `backup-main-before-ai`（需审批） |

**禁止**执行 `docker compose down -v`，不要删数据库、Redis、COS 数据。

## 13. 常见失败速查

| 现象 | 原因与处理 |
| --- | --- |
| SSH 连不上 | 安全组 22 端口/来源 IP；用腾讯云控制台 WebShell 应急 |
| psql 报 `no pg_hba.conf entry` | `hostssl` 行没写对，或重启后未生效 |
| psql 报 SSL 错误 | 证书路径/权限不对；`server.key` 必须 600 |
| 80/443 打不开 | 安全组和 ufw 都要放行 |
| Caddy 证书失败 | DNS 未生效或 80 端口不通；等几分钟重试 |
| `api` 一直不 healthy | `docker compose logs api`；通常是数据库/Redis 连不上或 COS 配置错误 |
| Docker 拉镜像超时 | 按 `DEPLOY_GUIDE.md` 4.1/4.2 配置国内镜像源并换源重试 |
| npm 构建超时 | 构建时加 `--build-arg NPM_REGISTRY=https://registry.npmmirror.com` |
| 首页没有 AI 卡片 | `AI_IMAGE_EXTERNAL_URL` 未配置，或合并到 main 后未重新部署 |
| 登录后 Gallery 仍显示游客 | `SESSION_COOKIE_DOMAIN` 或 introspection 密钥不一致 |
| 图片上传 COS 403 | CAM 策略地域/桶名/账号ID 写错，或服务器时间不准 |
| 公开图片 403 | 桶策略没有放行 `images/jobs/*` |
| 积分不足 | 新用户首次进创建页才到账；`BILLING_SIGNUP_GRANT=0` 表示关闭 |
| Caddy 报 `address already in use`（443） | 服务器上有 Tailscale 占用端口：`sudo systemctl stop tailscaled && sudo systemctl disable tailscaled`，再重建 caddy |
| Caddy 容器没有网络（`docker inspect ... NetworkSettings.Networks` 为 `{}`） | `docker compose ... up -d --force-recreate --no-build caddy` 强制重建 |
| 容器内 DNS 报 `network is unreachable` 或 `127.0.0.53` 拒绝 | 在 `/etc/docker/daemon.json` 配置 `"dns": ["223.5.5.5", "119.29.29.29"]` 后重启 Docker |
| dispatcher/worker 报 `DEPTH_ZERO_SELF_SIGNED_CERT` | `DATABASE_URL` 加 `uselibpqcompat=true&sslmode=require`（自签证书场景，node pg 客户端兼容 libpq 语义） |
| api 报 `[ioredis] ETIMEDOUT` | `REDIS_URL` 必须写 `redis://redis:6379`（内网 Redis 无 TLS），并保持 `ALLOW_PLAINTEXT_REDIS=true` |
