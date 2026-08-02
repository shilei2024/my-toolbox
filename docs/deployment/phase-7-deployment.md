# Phase 7 部署与回滚手册

## 部署顺序

1. 运行 Generation Service 类型检查、常规测试与 PostgreSQL SEO 集成测试。
2. 部署 Generation Service，确认签名请求可访问 `GET /v1/seo/images?limit=1`。
3. 为 Next.js 配置 `GALLERY_PUBLIC_ORIGIN`、`GALLERY_SERVICE_BASE_URL` 和 `GALLERY_INTERNAL_HMAC_SECRET`。
4. 部署 Next.js，依次检查 `/robots.txt`、`/sitemap.xml`、`/opengraph-image` 和一个公开作品页。
5. 检查作品页 canonical、OG、Twitter 与 `application/ld+json`，确认源码中不存在隐藏 Prompt。
6. 提交 Sitemap；先观察抓取与服务器负载，再扩大搜索入口。

## 上线检查

- `GALLERY_PUBLIC_ORIGIN` 必须是最终 HTTPS origin，不得包含路径、查询串或凭据。
- COS/CDN 图片 hostname 必须存在于 `GALLERY_ASSET_HOSTS`。
- 反向代理不得缓存认证作品 HTML；公开 metadata 可由 Next.js 正常缓存。
- `/v1/seo/images` 不应暴露到公网路由，只允许 Next.js 内部网络访问。
- Sitemap 返回失败时检查服务间 HMAC、数据库连接和公共资源 URL allowlist。

## 回滚

1. 回滚 Next.js 到 Phase 6 镜像，停止输出 sitemap/robots/动态 SEO；Gallery 浏览与互动保持可用。
2. 再回滚 Generation Service；`/v1/seo/images` 无写入副作用，无需数据库回滚。
3. 从搜索平台临时撤回 Sitemap；不要用全站 `Disallow` 作为长期回滚手段。
4. 已抓取的旧 URL 可继续返回 Gallery 正常页面；需要紧急去索引时，在页面级输出 `noindex`。
