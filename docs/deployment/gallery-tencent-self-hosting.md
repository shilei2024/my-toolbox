# Gallery 部署：仅 Vercel（腾讯云自托管方案已撤销）

> 状态：**已撤销（2026-08-09）**，见 ADR-0023。
>
> Gallery Web（`apps/gallery-web`）只部署在 Vercel，`gallery.mindfulpenpal.com`
> 保持 CNAME → `cname.vercel-dns.com`。腾讯云服务器**不运行** Gallery 容器，
> 也不需要 `GALLERY_WEB_IMAGE` / `GALLERY_WEB_DOMAIN` / `GALLERY_PUBLIC_ORIGIN`
> 等变量。本页保留给已经按旧方案动过服务器的运维人员，说明如何清理现场。

## 为什么撤销

- Gallery 的页面渲染问题（CSP nonce）已在 Vercel 部署上修复，未发现必须自托管的阻塞项；
- 自托管需要额外维护 Docker 镜像、Caddy 站点、DNS A 记录和服务器资源，与主站仍在
  Vercel 的现状形成两套入口和两套发布流程；
- 服务器应只承担 Generation Service（api / dispatcher / worker / deletion-worker）
  与 `api-ai` 入口的职责。

## 服务器清理步骤（如果你之前已经启用过 Gallery 容器）

1. 更新服务器代码到包含 ADR-0023 的发布版本（compose 与 Caddy 已移除 Gallery）：

```bash
cd /opt/mindfulpenpal
git fetch origin --tags
git checkout <release>
git pull --ff-only
```

2. 停止并删除旧的 Gallery 容器（只动 gallery，不影响其他服务）：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml stop gallery
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml rm -f gallery
```

3. 用新编排重建其余服务（api / dispatcher / worker / deletion-worker / caddy）：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile production up -d --no-build
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml ps
```

4. （可选但建议）从 `/etc/mindfulpenpal.production.env` 删除只属于 Gallery 容器的变量：
   `GALLERY_WEB_IMAGE`、`GALLERY_WEB_DOMAIN`、`GALLERY_SERVICE_BASE_URL`、
   `MAVIS_AUTH_INTROSPECTION_URL`、`MAVIS_AUTH_SESSION_COOKIE_NAME`、
   `GALLERY_PUBLIC_ORIGIN`、`MAVIS_AUTH_LOGIN_URL`、`MAVIS_AUTH_LOGOUT_URL`。
   保留 `GALLERY_CURSOR_SECRET`、`GALLERY_INTERNAL_HMAC_SECRET`、`GALLERY_ASSET_HOSTS`
   （Generation Service 仍在使用）。`GALLERY_INTROSPECTION_SECRET` 本来就只配置在
   Vercel 的两个项目里，服务器不需要。

5. 确认 DNS：`gallery` 记录必须是 CNAME → `cname.vercel-dns.com`（如果之前改成
   过 A 记录，改回来，等待 TTL 生效）。

## 验证

```powershell
Resolve-DnsName gallery.mindfulpenpal.com
curl.exe -I https://gallery.mindfulpenpal.com/gallery
curl.exe https://gallery.mindfulpenpal.com/api/me/session
```

预期：DNS 返回 Vercel 的 CNAME 链；响应头 `Server: Vercel`，且
`Content-Security-Policy` 包含 `script-src ... 'nonce-...'`；
未登录会话接口返回 `{"role":"guest","bridge":"guest"}`。

## 日常发布（Vercel-only）

1. 合并 PR 到 `main`，Vercel Gallery Web 项目（Root Directory `apps/gallery-web`，
   Production Branch `main`）自动生产部署；
2. 环境变量只配置在 Vercel Dashboard 的 Production / Preview；
3. 发布后验证 `/gallery` 不卡骨架、CSP 带 nonce、登录/创建/任务中心正常。

详细步骤见 [Vercel 前端部署指南](vercel-deployment.md)。
