# ADR 0023: Gallery stays on Vercel (Tencent self-hosting withdrawn)

## Status

Accepted — 2026-08-09. Supersedes ADR-0022.

## Why

ADR-0022 曾把 Gallery Web 从 Vercel 切到腾讯云自托管，以改善中国大陆访问。后续评估：
Vercel 部署已经满足当前业务与运维流程（CI、Preview、回滚、环境变量管理均为既有流程）；
自托管需要额外维护 Docker 镜像、Caddy 路由、DNS A 记录和服务器资源，并与主站仍在
Vercel 的现状形成两套入口；Gallery 页面渲染问题（CSP nonce）已在 Vercel 部署上修复，
未发现必须自托管的阻塞项。

## Decision

Gallery Web 仅部署在 Vercel（项目 Root Directory 为 `apps/gallery-web`，Production
Branch 为 `main`），`gallery.mindfulpenpal.com` 保持 CNAME → `cname.vercel-dns.com`。
腾讯云服务器只运行 Generation Service（api / dispatcher / worker / deletion-worker）
与 Caddy（`api-ai` 与主站代理），不再包含 Gallery 容器、Gallery Caddy 站点或
`GALLERY_WEB_*` 环境变量。仓库删除 `apps/gallery-web/Dockerfile`、`.dockerignore`
与 Next.js `output: "standalone"`，部署编排与部署文档同步改为 Vercel-only。

## Alternatives Considered

1. 保留腾讯云自托管（ADR-0022）：增加运维面与两套部署流程，收益不明确。
2. Caddy 反向代理 Vercel：仍然依赖跨境链路，还额外增加一跳，未解决根因。

## Future Impact

若未来中国大陆访问再次成为硬性需求，应优先评估 CDN 回源（腾讯云 CDN 回源 Vercel 或
对象存储/CDN 分发），而不是把 Next.js BFF 搬上单台 CVM。服务器职责保持单一：
Generation Service 与 `api-ai` 入口。

## Performance

浏览器到 Gallery 走 Vercel 边缘；Gallery BFF 到 `api-ai` 的调用由 Vercel 发起，如遇
跨境链路不稳定，可复用 Cloudflare Worker / 隧道方案（见
`gallery-integration-cloudflare-tunnel.md`），不改变部署边界。

## Cost

删除 Gallery 容器后服务器 CPU/内存占用下降；Vercel 侧成本不变。

## Security

服务器不再运行 Gallery BFF，减少一个容器与一组密钥的暴露面；Vercel 上的 CSP nonce、
HMAC、introspection 配置保持不变。

## Rollback Plan

如需恢复自托管，按 ADR-0022 的原始步骤重新构建镜像、配置 DNS 与 Caddy；Vercel
部署始终作为即时回滚目标可用。
