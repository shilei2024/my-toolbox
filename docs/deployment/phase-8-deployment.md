# Phase 8 部署与回滚手册

## 部署顺序

1. 备份 PostgreSQL，并在同版本临时实例 dry-run migration 0001–0003。
2. 执行 `0003_admin_console.sql`；该 migration 只增加索引。
3. 部署 Generation Service，验证普通用户访问 `/v1/admin/dashboard` 为 403。
4. 使用测试管理员验证 dashboard 和一次无风险 Workflow 排序更新。
5. 部署 Next.js，验证 `/admin` 为 `noindex,nofollow`，跨 Origin 写请求为 403。
6. 执行一次审核操作，确认图片公开状态、Gallery 缓存失效、`moderation_events` 和 `audit_logs` 同步产生。
7. 配置统一后台：Flask 设置 `GALLERY_SERVICE_BASE_URL` 与 `GALLERY_INTERNAL_HMAC_SECRET`，
   Vercel 设置 `MAVIS_ADMIN_URL` 与 `NEXT_PUBLIC_MAVIS_ADMIN_URL`；主站 `/admin/gallery` 可读可写，
   Gallery `/admin` 自动跳转主站，导航栏向管理员显示“后台”。

## 配置

Phase 8 不新增密钥。继续复用：

- `GALLERY_SERVICE_BASE_URL`
- `GALLERY_INTERNAL_HMAC_SECRET`
- `MAVIS_AUTH_INTROSPECTION_URL`
- `GALLERY_INTROSPECTION_SECRET`
- `GALLERY_PUBLIC_ORIGIN`
- `MAVIS_ADMIN_URL` / `NEXT_PUBLIC_MAVIS_ADMIN_URL`（统一后台入口）

Flask `public.users.is_admin` 是当前角色事实。生产环境应限制 Generation Service 只允许 Next.js/BFF 私网访问，并为管理员账户启用强密码和后续 MFA。

## 监控

- 按 `admin.*` action 监控写操作与异常增长。
- 监控 401/403、409 和 429；大量 409 可能表示多管理员同时操作或页面长期未刷新。
- 对 Provider 被禁用、Workflow 被停用和大批量拒绝设置告警。
- 定期检查审计保留策略；Phase 10 支付上线后延长保留期。

## 回滚

1. 先回滚 Next.js，隐藏 Admin UI 和 BFF routes。
2. 再回滚 Generation Service，Admin routes 消失，生成、Gallery 和 SEO 继续运行。
3. `0003` 索引可保留且不会影响旧版本；如确需移除，使用新的受控 migration `DROP INDEX CONCURRENTLY`，不要回写历史 migration。
4. 已完成的审核和配置变更属于业务事实，不随代码回滚自动撤销；需要通过新管理操作或审计指导的 SQL 补偿恢复。
