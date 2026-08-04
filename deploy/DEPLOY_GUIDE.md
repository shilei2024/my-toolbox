# MindfulPenpal AI 增强版 · 生产部署指南（非程序员版）

本文面向没有任何 DevOps 经验的部署人员。每个步骤都说明：为什么做、执行什么命令、预期看到什么、失败怎么办。

## 0. 你要部署的东西长什么样

```text
用户浏览器
   ├─ mindfulpenpal.com        → Vercel 上的原网站（Flask，登录/注册/工具）
   │      └─ 首页“AI 作图”卡片 → 跳到 https://<gallery域名>/create
   └─ <gallery域名>            → Vercel 上的 Gallery Web（Next.js BFF）
                                    │ 内部调用（HMAC 签名）
                                    ▼
                              腾讯云服务器（Docker）
                                  ├─ Generation API（创建任务/查询/取消）
                                  ├─ Dispatcher（把数据库任务投递到队列）
                                  ├─ Worker（调用 AI Provider、上传 COS）
                                  ├─ 删除 Worker（延迟清理 COS 对象）
                                  └─ Caddy（HTTPS 反向代理）
  PostgreSQL（用户表 + ai schema）   Redis（BullMQ 队列）   腾讯云 COS（图片）
```

关键概念：**原网站不会消失**。合并后原网站功能不变，AI 作图只是首页上的一个新入口；入口地址没配置时，卡片自动隐藏。

## 1. 准备清单（先确认再动手）

发布前逐项确认，缺任何一项都不要继续：

> 还没买过任何腾讯云资源？先读 [腾讯云资源准备指南（小白版）](../docs/deployment/tencent-cloud-setup-guide.md)，从购买服务器、建 COS 桶、创建最小权限密钥到 DNS 全部有逐步点击教程；本指南假设这些资源已经就绪。

- [ ] GitHub 仓库已有 `main` 与 CI 通过（合并后 CI 会跑 Python / Generation / Gallery 测试）
- [ ] Vercel 上有**两个项目**：原 Flask 项目（Root Directory 为仓库根目录）与 Gallery Web 项目（Root Directory 为 `apps/gallery-web`）
- [ ] `mindfulpenpal.com` 的当前生产 deployment ID 已截图记录（回滚用）
- [ ] 腾讯云服务器：2 核 4 GB 以上、Ubuntu 22.04/24.04、开放 22/80/443 端口
- [ ] 已购买/创建：PostgreSQL（推荐托管）与 Redis（生产必须 TLS `rediss://`），或确认使用本机容器（local-infra）
- [ ] 腾讯云 COS Bucket + 最小权限 CAM 子账号密钥（仅允许该 Bucket 上传/读取/删除）
- [ ] 至少一个真实 AI Provider 密钥：OpenAI、Gemini 或 即梦/Seedream
- [ ] 已规划域名：`api-ai.<你的域名>`（后端）与 `<gallery域名>`（前端），DNS 已解析

> 为什么先记录 deployment ID：Vercel 回滚就是“把域名切回旧 deployment”，没有 ID 无法验证回滚目标。

## 2. 服务器准备

登录服务器（Windows 用 PowerShell 或终端）：

```bash
sudo apt update && sudo apt upgrade -y
```

安装 Docker（腾讯云国内源会更快）：

```bash
> 服务器和 COS 已经存在，并且要把原站数据库搬到腾讯服务器？
> 先看 [已有服务器与 COS 的生产部署（数据库搬迁版）](../docs/deployment/tencent-existing-server-setup.md)，
> 本文其余章节按“从零购买资源”继续。

curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

退出重新登录后验证：

```bash
docker version
```

预期：Client 和 Server 两段都显示版本号。只显示 Client 说明 Docker 没启动，执行 `sudo systemctl start docker`。

## 3. 获取代码并创建环境文件

```bash
sudo mkdir -p /opt/mindfulpenpal
sudo chown $USER /opt/mindfulpenpal
git clone https://github.com/shilei2024/my-toolbox.git /opt/mindfulpenpal
cd /opt/mindfulpenpal
```

把模板复制成真实环境文件：

```bash
sudo install -o root -g root -m 600 /dev/null /etc/mindfulpenpal.production.env
sudo cp deploy/.env.production.example /etc/mindfulpenpal.production.env
sudo chmod 600 /etc/mindfulpenpal.production.env
sudo nano /etc/mindfulpenpal.production.env
```

逐项替换 `replace_...` 占位符。最容易填错的三项：

| 变量 | 填什么 | 常见错误 |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://用户:密码@主机:端口/数据库` | 忘记 TLS/白名单，或填成 `postgres://`（程序会自动转换，但建议直接写 `postgresql://`） |
| `REDIS_URL` | `rediss://...` | 生产写成 `redis://` 会被预检拒绝 |
| `GENERATION_IMAGE` | 仓库里的 `镜像@sha256:64位十六进制` | 填 `latest` 会被预检拒绝 |

> 为什么权限要 600：这个文件里有数据库密码和 AI 密钥，只有 root 能读，避免其他用户/进程读取。

## 4. 国内网络优化（Docker 镜像源与 npm）

### 4.1 Docker 镜像源

腾讯云服务器有免费内网镜像加速。编辑 Docker 配置：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com",
    "https://docker.m.daocloud.io"
  ]
}
EOF
sudo systemctl restart docker
```

验证：

```bash
docker info | grep -A 3 "Registry Mirrors"
```

预期出现两个 mirror 地址。

### 4.2 Docker 拉取失败的处理

- 现象：`docker pull` 卡住、`timeout`、`dial tcp: i/o timeout`。
- 第一步：换镜像源（上面两个不够就临时只留一个，再重启 Docker 重试）。
- 第二步：把镜像改从国内镜像仓库地址拉取，例如 `docker pull docker.m.daocloud.io/library/postgres:16-alpine`，再 `docker tag` 成原名称。
- 第三步：如果镜像已发布到腾讯云 TCR（`ccr.ccs.tencentyun.com`），优先从 TCR 拉取；构建机在境外时也可以让 GitHub Actions 构建后推送 TCR。
- 不要反复重试同一个失败源超过 3 次，先换源。

### 4.3 npm 使用 npmmirror

国内服务器执行 npm 安装前设置：

```bash
npm config set registry https://registry.npmmirror.com
```

或在项目目录创建 `.npmrc`：

```bash
echo "registry=https://registry.npmmirror.com" > .npmrc
```

> 本仓库 `apps/gallery-web/.npmrc` 属于个人机器配置，不会提交；部署机上按上述命令配置即可。CI（GitHub）使用默认 registry，不受影响。

## 5. 镜像构建与预检

后端镜像构建（在仓库根目录）：

```bash
cd /opt/mindfulpenpal/services/generation-service
docker build -t mindfulpenpal/generation-service:<版本号> .
cd /opt/mindfulpenpal
```

> 生产强烈建议把构建产物推送到私有镜像仓库（腾讯云 TCR），用 `@sha256` digest 部署，而不是在服务器上每次构建。

预检（不输出任何密钥值）：

```bash
sh services/generation-service/deploy/preflight-production.sh /etc/mindfulpenpal.production.env
```

预期输出：

```text
production preflight passed; no secret values were printed
```

如果失败，只修改提示的变量，不要贴日志里的真实值。

## 6. 数据库迁移

如果你使用**本机容器数据库（local-infra）**，先启动数据库并等待 healthy：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile local-infra up -d postgres redis
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile local-infra ps
```

预期：`postgres`、`redis` 状态为 `healthy`。托管数据库模式跳过这一步。

先备份（托管 PostgreSQL 在控制台创建备份；本地容器用）：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile local-infra exec -T postgres \
  pg_dump -U mavis mindfulpenpal > /opt/mindfulpenpal/backup-$(date +%F).sql
```

执行迁移（会按顺序应用 0001-0007，全部为新增 schema，不删除旧数据）：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile migration run --rm migrate
```

> 本地容器模式请把 `--profile migration` 换成 `--profile migration --profile local-infra`，确保迁移容器能连到同网络的 `postgres` 服务。

预期：每个 `database/migrations/000N_*.sql` 都输出 `applying migration:`，最后没有报错。重复执行会跳过已应用的迁移。

## 7. 启动后端

托管 PostgreSQL/Redis（推荐）：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile production up -d --no-build
```

本机容器数据库（仅小型/验收环境）：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile local-infra --profile production up -d --no-build
```

查看状态：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml ps
```

预期：`api` 状态为 `healthy`，`dispatcher`、`worker`、`deletion-worker`、`caddy` 为 `running`。

健康检查：

```bash
curl https://<api-ai域名>/health
```

预期：`{"status":"ok"}`。

## 8. 配置 Vercel（原网站 + Gallery Web）

### 8.1 原 Flask 项目（mindfulpenpal.com）

在 Vercel 项目 Settings → Environment Variables → Production 添加：

| 变量 | 值 |
| --- | --- |
| `GALLERY_INTROSPECTION_SECRET` | 与服务器环境文件中的值完全一致（至少 32 字节） |
| `SESSION_COOKIE_DOMAIN` | `.mindfulpenpal.com`（注意开头的点；只有确认共享父域才设置） |
| `SESSION_COOKIE_SECURE` | `true` |
| `AI_IMAGE_EXTERNAL_URL` | `https://<gallery域名>/create` |

> 风险提示：`SESSION_COOKIE_DOMAIN` 配置错误会让整个站点的登录 Cookie 失效。先在 staging 子域验证，再上生产。

### 8.2 Gallery Web 项目（apps/gallery-web）

在 Gallery Web 项目的 Production 环境添加：

| 变量 | 值 |
| --- | --- |
| `GALLERY_SERVICE_BASE_URL` | `https://<api-ai域名>` |
| `GALLERY_INTERNAL_HMAC_SECRET` | 与服务器一致 |
| `MAVIS_AUTH_INTROSPECTION_URL` | `https://mindfulpenpal.com/auth/internal/gallery/session` |
| `GALLERY_INTROSPECTION_SECRET` | 与 Flask 一致 |
| `GALLERY_PUBLIC_ORIGIN` | `https://<gallery域名>` |
| `MAVIS_AUTH_LOGIN_URL` | `https://mindfulpenpal.com/login` |
| `MAVIS_AUTH_LOGOUT_URL` | `https://mindfulpenpal.com/logout` |

确认 Gallery Web 项目的 Root Directory 是 `apps/gallery-web`、Production Branch 是 `main`。所有变量都不要加 `NEXT_PUBLIC_` 前缀。

> Vercel 新版界面入口：Project → Settings → Environments → **Production** 区块 → “Git Branch” 选择 `main`
> 并保存（旧版 Settings → Git 的 “Production Branch” 已迁移到 Environments）。
> 找不到下拉框时，可到 Deployments 页对来自 `main` 的最新部署点 “Promote to Production”。

## 9. 启用 AI Provider

1. 浏览器登录原站后台 `/admin`。
2. 打开“运营控制台”（Gallery Web 的 `/admin`，管理员账号共用原站）。
3. Provider 列表中找到已配置密钥的 Provider（如 `openai`），把状态从 `disabled` 改为 `active`。
4. 首页/创作页 `/create` 出现可用的创作方式。

> 默认所有 Provider 都是 disabled，这是故意的安全设计：不启用就不会产生任何真实费用。

## 10. 上线验收

按 [上线验收清单](../docs/deployment/ai-merge-acceptance.md) 逐项验收，特别是：

1. `mindfulpenpal.com` 打开正常、登录正常。
2. 首页出现“AI 作图”卡片并跳到 Gallery。
3. 新注册用户首次进入创建页获得赠送积分。
4. 创建任务 → 积分预占 → Worker 调用 Provider → COS 落盘 → Gallery 显示。
5. 图片按 `GALLERY_DEFAULT_MODERATION` 显示（生产默认待人工审核）。

## 11. 回滚（万一出问题）

### 前端回滚（最快）

Vercel Deployments 页面选择上一个健康 deployment → Promote/Rollback。验证域名、登录、首页。

### 后端回滚

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml stop dispatcher worker api caddy
```

把 `GENERATION_IMAGE` 改回旧 digest，再 `up -d --no-build`。**不要**执行 `down -v`，不要删除数据库、Redis、COS 数据。

### 数据库

迁移只新增 `ai` schema 与目录数据，不需要 down migration。恢复策略是：用备份库验证后切换 `DATABASE_URL`，而不是删除新表。

## 12. 常见失败速查

| 现象 | 原因与处理 |
| --- | --- |
| `docker pull` 超时 | 镜像源问题，见 4.2 |
| 预检失败 | 环境文件有占位符/缺少变量，按提示修改 |
| `api` 一直不 healthy | 看日志 `docker compose logs api`；通常是数据库/Redis 连不上或 COS 配置错误 |
| 首页没有 AI 卡片 | `AI_IMAGE_EXTERNAL_URL` 未配置或不是 HTTPS，配置后重新部署 |
| 登录后 Gallery 仍显示游客 | `SESSION_COOKIE_DOMAIN` 或 introspection 密钥不一致 |
| 创建任务一直 pending | 看 dispatcher 日志与 outbox；Redis 未连接时任务不会投递 |
| 创建任务一直 running | 看 worker 日志；Provider 未启用/密钥错误/COS 不可写 |
| 积分不足 | 新用户首次打开创建页才会到账；`BILLING_SIGNUP_GRANT=0` 表示关闭赠送 |
| Gallery 没有公开作品 | `GALLERY_DEFAULT_MODERATION=pending` 时需要管理员在后台批准 |
