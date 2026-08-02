# ADR-0007：Guest 视角公开图片 SEO、最小 Sitemap 接口与服务端结构化数据

状态：Accepted  
阶段：Phase 7

## Why

每个公开作品都应成为长期可发现的社区内容，但 SEO 输出不能复用 owner/admin 视角，否则隐藏 Prompt、私有状态或内部 Provider 信息可能进入 HTML、社交卡片或爬虫缓存。选择由 Next.js SSR 生成 metadata 和 JSON-LD，并始终通过 HMAC 认证的 Guest 视角读取公开作品；Sitemap 使用 Generation Service 的最小专用接口和 PostgreSQL keyset cursor。搜索/筛选参数页不建立独立索引，以避免重复内容和无限抓取空间。

## Alternatives Considered

- 让 Next.js 直连 PostgreSQL生成 Sitemap：查询少一跳，但破坏 Phase 1/6 服务边界并扩大数据库暴露面。
- 在浏览器运行时写入 metadata：爬虫兼容性差，首个 HTML 不完整，且容易泄露账户态数据。
- 直接复用完整 `/v1/gallery` 批量分页：无需新接口，但每条记录包含无关展示字段、标签和 viewer flags，50,000 条时成本显著更高。
- 把 Prompt 拼入 SEO 描述：可能提升长尾词覆盖，但违反 hidden Prompt 语义，也增加敏感内容和注入风险。
- 为每个搜索词、筛选组合生成索引页：入口多，但产生重复/低质量页面和无限 URL 空间。
- 立即使用 Elasticsearch/Typesense 生成 SEO 分类页：能力强但引入额外基础设施、同步链路和成本，当前阶段没有必要。
- 构建时生成静态 Sitemap：实现简单，但新作品必须重新构建才能出现，时效性差。

## Future Impact

Phase 8 管理后台应提供 SEO 可见性诊断和 moderation 状态检查，但不得绕过 Guest 视角规则。Phase 9 新 Provider 不改变 SEO 契约；Provider 名称默认不进入结构化数据。Phase 10 会员/积分页应独立设置索引策略。公开作品超过 50,000 时，需要使用 Next.js `generateSitemaps` 或独立 sitemap index 分片；标签或工作流专题页只有在具备真实策展文案和足够作品后才应加入 Sitemap。

## Performance

SEO feed 只查询三类业务字段和首选公共资产，复用 `(published_at DESC, id DESC)` 部分索引，避免 offset 深页扫描；每批最多 1,000 条。Sitemap 缓存一小时，正常抓取不会持续压数据库。详情页 metadata 通过 React request cache 复用同请求读取；认证用户页面仍额外执行 Guest 读取，以保证 SEO 隔离，代价是一条受缓存保护的公开详情查询。

## Cost

不引入搜索集群、第三方 SEO API 或新数据库。新增成本主要是每小时 Sitemap 刷新、爬虫访问 SSR 页面和 COS/CDN 图片流量。使用真实缩略图/公共资产、最小接口和缓存控制请求量。品牌分享图在构建期离线生成，不依赖付费字体或外部图像服务。

## Security

SEO 接口仍要求短时 HMAC 服务身份且建议只在内部网络开放。数据库查询只接受签名 keyset cursor，没有自由 SQL、搜索词或用户 ID。只有 `public + approved + published + not deleted` 图片可输出。JSON-LD 对 `<` 做 Unicode 转义，文本折叠并限长；public origin 仅接受 HTTPS，loopback HTTP 只供开发。私有页、个人页和参数页设置 `noindex`，robots 禁止 API 与后台抓取。Prompt、negative prompt、Provider 路由、COS 密钥和签名 URL不进入 SEO 输出。

## Rollback Plan

先回滚 Next.js Phase 7 版本，公开 Gallery 会恢复 Phase 6 基础页面；再回滚 Generation Service，未使用的 `/v1/seo/images` 路由消失。Phase 7 没有数据库迁移或持久化写入，因此无需数据回滚。若只有 Sitemap 负载异常，可临时将其降级为 `/gallery` 单条基础 Sitemap；若 metadata 内容错误，可部署页面级 `noindex` 并在搜索平台请求重新抓取。回滚期间保留正常作品 URL，避免用 404 或全站 robots 禁止造成长期索引损失。
