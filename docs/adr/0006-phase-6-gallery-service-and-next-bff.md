# ADR-0006：Gallery Service 模块、Next.js SSR/BFF 与延迟对象删除

状态：Accepted  
阶段：Phase 6

## Why

Gallery 同时涉及公开读、私有图片、Prompt 字段过滤、互动计数、owner/admin 删除、COS URL 和审计，不能把这些规则散落到浏览器或让 Next.js 直接访问数据库。选择在 Generation Service 模块化单体中建立 Gallery 领域模块和 API，Next.js 只负责 SSR/BFF；Flask 继续作为现有登录事实来源。公开 feed 使用 PostgreSQL keyset cursor，删除采用事务性软删除加独立对象清理任务。

## Alternatives Considered

- Next.js/Vercel 直连 PostgreSQL：代码少，但数据库需暴露到跨云网络，权限与事务会分裂到前端项目。
- 在 Flask 中实现全部 Gallery：复用登录最直接，但会把新平台业务重新耦合回旧站，削弱 Phase 1 的服务边界。
- 立即建立独立 Gallery 微服务：隔离更强，但早期多一套部署、鉴权、监控和数据库协调，成本高于收益。
- offset pagination：实现简单，但深页扫描慢，新增内容会造成重复/跳项。
- Redis 保存 Gallery 事实：读取快，但缓存清理后会丢失业务状态，因此只作为短 TTL 加速。
- 删除 API 同步删除 COS：路径直观，但 COS 短暂故障会拉长请求或产生数据库/COS 双写不一致。
- 数据库级 RLS：纵深防御强，但现有连接池和 `public.users` 迁移尚未提供稳定 per-request DB role；本阶段使用集中 repository 条件、事务和测试，保留未来加入 RLS 的可能。
- 把邮箱作为创作者名称：无需新表，但泄露个人身份，因此新增最小公开 profile。

## Future Impact

Phase 7 可在同一 Next.js 详情数据上增加 canonical、OG、Twitter Card、JSON-LD 和 sitemap，不改变 Gallery API。Phase 8 管理后台可复用 admin viewer context、审计表和 deletion task。Phase 9 多 Provider 只会增加展示元数据，不改变 Gallery 路由；删除 worker 已按 storage provider 路由，未来可注册 OSS/S3/R2 adapter。Phase 10 会员权限可在 viewer/entitlement 层增加，不允许前端自报等级。

## Performance

混合降序索引和 HMAC keyset cursor 避免深页 offset 扫描。列表用 lateral query 一次取得首选资产、标签和 viewer flags，避免 N+1 数据库查询；私有 URL 签名只发生在可访问内容上。Guest 缓存默认 30 秒并通过 namespace version O(1) 失效。互动触发器增加一次行更新，但换取跨写入路径计数一致性；热门单图可能成为行热点，达到瓶颈后再引入异步聚合。

## Cost

Next.js SSR、Gallery API 和 deletion worker 增加少量 CPU/内存；不增加搜索集群或新消息系统。继续使用 PostgreSQL、现有 Redis 和腾讯云 COS，适合低成本起步。CDN/缩略图降低源图流量；短 TTL cache 减少重复查询。删除 worker 使用低频数据库轮询，避免为低吞吐清理任务单独建立队列。

## Security

浏览器只访问同源 BFF。Next.js 通过受保护的 Flask introspection 验证 Session，再签发 60 秒 HMAC 用户上下文；Generation Service 不信任浏览器 user ID。写操作检查 Origin，服务端限流，错误响应脱敏。公开 URL 必须是 HTTPS 且 hostname 在 COS/CDN allowlist；私有图片使用短时 COS 签名 URL。隐藏 Prompt 仅 owner/admin 返回且不进入公开搜索/缓存。删除、互动和敏感访问保留 audit/download log，日志不包含 Cookie、Prompt、密钥或签名 URL 查询串。

## Rollback Plan

先通过反向代理/feature flag 停止新 Gallery 流量并停止 deletion worker，再回滚 Next.js 和 API 镜像。`0002` 只增加表、索引、类型和触发器，Phase 5 代码可继续运行，因此默认保留数据库增量而不执行破坏性 down migration。retention 内的误删可清除 `deleted_at` 并取消 deletion task；物理删除后依赖 COS 版本控制/备份恢复。Redis cache 可随时禁用，不影响 PostgreSQL 事实。若身份桥异常，系统 fail closed 为 Guest，私有数据和写操作不可用但公开 Gallery 可继续读取。
