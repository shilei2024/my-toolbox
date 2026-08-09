# Gallery 国内访问修复：腾讯云自托管

## 目的与边界

`gallery.mindfulpenpal.com` 之前直接解析到 Vercel。该入口在中国大陆网络中不稳定，即使 Vercel
部署本身健康，用户也可能无法打开 Gallery。本方案将 **Gallery Web（Next.js BFF）运行在现有腾讯云
服务器**，由同一台 Caddy 提供 HTTPS；域名、Cookie 范围和对外 API 契约均不变。

这不是把 COS 设为公网桶，也不会把 Generation API 暴露到新端口。Vercel 的 Gallery 项目保留，作为
可回退的备用部署；主站仍按现有方式部署。

```text
浏览器（中国大陆）
   │ https://gallery.mindfulpenpal.com
   ▼
腾讯云 CVM / Caddy ──► Gallery Web（Next.js，Docker :3000）
   │                         │ HTTPS（Docker host gateway）
   │                         ├────────► Flask 会话校验（:8000）
   │                         └────────► Generation API（Docker :3101）
   ▼
腾讯云 COS
```

## 上线前检查

1. 仅在已验证的发布分支/提交上执行；不要直接修改线上 `main` 的未审查内容。
2. 服务器安全组已放行 TCP `80`、`443`，并且现有 Caddy 正常托管
   `api-ai.mindfulpenpal.com`。
3. 保存当前 DNS 记录、当前 Caddy 容器日志，以及 `/etc/mindfulpenpal.production.env` 的离线备份。
   备份文件不可提交或发送到聊天。
4. 将 `gallery` 的 TTL 提前降到 60–300 秒，等待旧 TTL 过期后再切换，便于回滚。

## 1. 构建并校验镜像

在服务器仓库目录执行。将 `<release>` 替换为已审核的 tag 或 commit；不要使用 `latest`。

```bash
cd /opt/mindfulpenpal
git fetch origin --tags
git checkout <release>
git pull --ff-only

docker build --build-arg NPM_REGISTRY=https://registry.npmmirror.com \
  -t mindfulpenpal/gallery-web:<release> apps/gallery-web

docker image inspect mindfulpenpal/gallery-web:<release> \
  --format '{{.Id}}'
```

预期最后一条输出一个 `sha256:` 镜像 ID。若构建失败，停止操作；现有 Vercel Gallery 不受影响。

## 2. 填写服务器环境变量

编辑 `/etc/mindfulpenpal.production.env`，保留所有已有 Generation Service 配置，并补充或更新以下项目。
真实密钥不得出现在终端历史、截图或文档中。

```ini
ALLOW_LOCAL_IMAGE_TAGS=true
GALLERY_WEB_IMAGE=mindfulpenpal/gallery-web:<release>
GALLERY_WEB_DOMAIN=gallery.mindfulpenpal.com

GALLERY_SERVICE_BASE_URL=https://api-ai.mindfulpenpal.com
GALLERY_INTERNAL_HMAC_SECRET=<与 Generation Service 已有值相同>
MAVIS_AUTH_INTROSPECTION_URL=https://mindfulpenpal.com/internal/gallery/session
MAVIS_AUTH_SESSION_COOKIE_NAME=mytoolbox_session
GALLERY_INTROSPECTION_SECRET=<与 Flask/Vercel 主站完全相同，至少 32 字节>
GALLERY_PUBLIC_ORIGIN=https://gallery.mindfulpenpal.com
MAVIS_AUTH_LOGIN_URL=https://mindfulpenpal.com/login
MAVIS_AUTH_LOGOUT_URL=https://mindfulpenpal.com/logout
```

`GALLERY_INTROSPECTION_SECRET` 必须同时保留在主站的 Vercel Production 环境变量中；它用于 Gallery
向 Flask 校验浏览器会话。不要把任何 URL 改为 `http://` 或 Docker 服务名：编排会把上述两个受控 HTTPS
域名安全地定向到本机 Caddy。

验证配置文件权限：

```bash
sudo chmod 600 /etc/mindfulpenpal.production.env
sudo stat -c '%a %U:%G %n' /etc/mindfulpenpal.production.env
```

预期权限为 `600 root:root`。

## 3. 先启动容器，再切 DNS

先由 Caddy 取得新配置。此时 DNS 仍指向 Vercel，Caddy 对 Gallery 的证书申请会等待，不影响已有的
`api-ai` 和主站代理。

```bash
cd /opt/mindfulpenpal
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile production up -d --no-build

docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml ps gallery caddy
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml logs --tail=100 gallery caddy
```

预期 `gallery` 为 `healthy`，并且 Caddy 没有 `gallery:3000` 上游连接错误。若 Gallery 不健康，执行
`docker compose ... logs gallery` 排查并停止在此处；不要变更 DNS。

## 4. 切换 DNS

在域名 DNS 控制台：

1. 删除 `gallery` 的 CNAME（`cname.vercel-dns.com`）。同一主机名不能同时存在 CNAME 和 A 记录。
2. 新增 `A` 记录：主机名 `gallery`，值为腾讯云服务器公网 IPv4，TTL 使用 60–300 秒。
3. 若存在 `gallery` 的 AAAA 记录，一并删除，除非服务器已验证可从公网 IPv6 访问且 Caddy 已监听 IPv6。

从服务器外的本地 PowerShell 验证：

```powershell
Resolve-DnsName gallery.mindfulpenpal.com
curl.exe -I https://gallery.mindfulpenpal.com/gallery
curl.exe https://gallery.mindfulpenpal.com/api/me/session
```

预期 DNS 返回腾讯云公网 IP；HTTP 响应包含 `Strict-Transport-Security`，会话接口在未登录时返回
`{"role":"guest","bridge":"guest"}`。证书尚未签发时，等待 1–5 分钟后检查 Caddy 日志；不要通过
关闭 TLS 或改用 HTTP 绕过。

## 5. 业务验收

在中国大陆网络完成以下检查：

1. 访问 `/`、`/gallery`、`/create`、`/tasks` 均可打开；刷新页面不会白屏。
   - 若 `/gallery` 只显示头部与加载骨架（正文不出现），说明部署的是旧构建：
     CSP 静态 `default-src 'self'` 会拦截 Next.js 流式渲染的内联脚本。必须重新
     构建含 `apps/gallery-web/src/proxy.ts` 的镜像，新构建的响应头
     `Content-Security-Policy` 应包含 `script-src ... 'nonce-...'`。
2. 未登录状态下 `/api/me/session` 返回 guest，登录后返回正确角色。
3. 创建任务、取消任务、查看任务中心；确认 Gallery BFF 仍只通过 HMAC 调用 Generation API。
4. 浏览一张 COS 图片，确认图片请求走预期的 COS/CDN 域名，而不是泄露私有桶对象键。
5. 在 Caddy 和 Gallery 容器日志中确认没有密钥、Cookie 或上游原始错误输出。

## 回滚

若 DNS 切换后任一步失败，先将 `gallery` 记录恢复为原来的 CNAME `cname.vercel-dns.com`，等待 TTL 生效；
这会恢复已验证的 Vercel Gallery。随后在服务器执行：

```bash
cd /opt/mindfulpenpal
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile production stop gallery
```

不要使用 `docker compose down -v`，不要删除 Caddy、数据库、Redis 或 COS 卷。回滚后保留日志，并在修复
镜像或配置后重新走“构建并校验镜像”开始的步骤。

## 运维说明

- 每次 Gallery 发布都构建新 tag 或不可变 digest，先在预览/测试环境验收，再更新
  `GALLERY_WEB_IMAGE` 并重新执行 `up -d --no-build`。
- `gallery` 容器限制为 512 MB；若频繁 OOM，先查日志、图片优化与请求峰值，再谨慎扩容。
- 该方案消除了浏览器直连 Vercel 的依赖，但主站若仍部署在 Vercel，主站自身的大陆可用性应作为独立
  风险跟踪，不要把两个问题混为一谈。
