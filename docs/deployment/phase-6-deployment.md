# Phase 6 部署与回滚手册

## 1. 部署顺序

1. 备份 PostgreSQL，并确认 `public.users.id` 是 integer。
2. 先部署兼容旧 schema 的 Generation Service 镜像，但暂不启动 Gallery 流量。
3. 执行 `0001_initial.sql`（未执行过时）和 `0002_gallery_system.sql`。
4. 配置 COS/CDN hostname allowlist、Redis 和三个独立 secrets。
5. 启动 Gallery API：`npm.cmd run gallery:start`。
6. 启动对象删除 worker：`npm.cmd run gallery:deletion-worker`。
7. 配置 Flask introspection secret 并部署 Flask。
8. 配置 Next.js Server Runtime 环境变量，执行 production build 并部署。
9. 先对内部 health、Guest feed、登录态、Prompt 隐私、收藏、删除做 smoke test。
10. 最后由反向代理把 `/gallery` 和 `/api/gallery|images|me` 切到 Next.js。

## 2. 数据库迁移

```powershell
psql $env:DATABASE_URL -v ON_ERROR_STOP=1 -f services/generation-service/database/migrations/0002_gallery_system.sql
```

迁移在单事务中执行。生产大表上的计数回填会持有写负载，应选择低峰期，并先在同规模 staging 数据上测量时间。

## 3. 进程建议

低成本初期可在同一 CVM 运行：

- Generation/Gallery API：1–2 个进程；
- Generation Worker：按 GPU 并发；
- Gallery deletion worker：1 个进程；
- Redis/PostgreSQL：生产推荐托管或独立实例。

Gallery API 可以横向扩容。分页无服务器 session；Redis cache 使用 namespace version；PostgreSQL transaction 和唯一约束负责一致性。

## 4. 健康与监控

- `GET /health` 只说明进程存活，不输出数据库、Redis、COS 或版本详情。
- 告警：5xx、PostgreSQL pool timeout、Redis latency、签名失败、429、deletion pending/failed/stalled 数量。
- 日志只记录 request/image/user ID、状态码和安全错误码，不记录 Prompt、Cookie、HMAC、COS 签名查询串或上游错误体。
- 定期核对聚合计数与互动表；数据库触发器是在线一致性的主保障。

## 5. Smoke tests

- 未签名直连 `/v1/gallery` → 401。
- 由 BFF 发起 Guest `/api/gallery` → 200。
- Guest 收藏 → 401；跨 origin 写请求 → 403。
- hidden Prompt：Guest 不返回字段，owner/admin 返回。
- private 图片：Guest 404，owner/admin 可见且 URL 有短时签名。
- 非 owner 删除 → 403；owner 删除后 feed/detail 立即不可见。
- COS 删除失败 → task failed + 延迟重试，不重新公开图片。

## 6. 回滚

应用回滚：先将反向代理 `/gallery` 切回旧页面或维护页，再回滚 Next.js 和 Gallery API 镜像。停止 deletion worker，避免回滚期间继续物理删除。

数据回滚：`0002` 是向前兼容的增量迁移，旧 Phase 5 代码不会读取新表，因此通常保留 schema，不做破坏性 down migration。若必须恢复误删图片，在 retention 到期前把 `images.deleted_at` 置空并把对应 deletion task 标记 `cancelled`；已经物理删除的 COS 对象只能从 COS 版本控制/备份恢复。

缓存回滚：可以直接禁用 `REDIS_URL` 使用 No-op cache；不要清空 BullMQ namespace。Gallery cache 与队列数据必须使用可区分前缀。
