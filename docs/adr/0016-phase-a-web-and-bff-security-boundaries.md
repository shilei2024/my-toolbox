# ADR-0016：Phase A Web 与 BFF 安全边界

状态：已接受（2026-08-09）

## Why

报销模块此前把匿名身份交给浏览器提供的请求头，并豁免全部写操作的 CSRF 校验；附件预览和 OCR 也没有把磁盘文件与属主同时校验。Gallery BFF 的管理员入口缺少本层角色保护，缺失 `Origin` 时仍允许写入。这些问题会让同源登录会话、私有附件和管理操作暴露于不必要风险。

## Decision

- 匿名报销数据统一使用 Flask 签名 session 内的 `anon_id`；不再接受 `X-RB-Anon-Id`。
- 所有报销和 ZIP 写请求恢复 Flask-WTF CSRF；前端从既有页面 meta token 发送 `X-CSRFToken`。
- 发票预览、附件回读与 OCR 必须用固定格式的 `file_id` 查询当前属主的持久化附件，不能用 glob 读取上传目录。
- ZIP 在解压前限制单成员未压缩大小、压缩比和递归累计解压量。
- 临时下载文件改为 128-bit 随机名，并在 Flask session 内保存短时下载授权；复制 URL 到其他 session 不可下载。
- `/diag` 仅在 DEBUG 或管理员会话下可见；Gallery 增加 CSP `frame-ancestors 'none'`、HSTS 与 `nosniff`。
- Gallery BFF 对所有写操作要求明确同源 `Origin`，对 `/api/admin/*`、兑换和创建生成任务先做角色检查；兑换和创建另有进程内节流。Generation Service 仍是分布式限流的权威层。
- 上游错误只允许预定义错误码及本地化安全文案返回浏览器。

## Alternatives Considered

1. 保留客户端匿名 ID 并加签名：签名密钥管理、轮换和前端迁移成本更高，且 Flask 已有 session 基础能力。
2. 仅依赖 SameSite Cookie：不能替代 CSRF token，也不能覆盖有害的同源子资源/旧浏览器场景。
3. 为临时下载建数据库表：可审计但对 30 分钟以内的低价值文件引入迁移、清理任务和运营成本；带过期的签名 session allow-list 足够且可复用。
4. BFF 使用 Redis 限流：生产应继续由 Generation Service 的共享限流实现；BFF 的本地节流作为无新基础设施的快速第二层保护。

## Future Impact

后续工具应复用 `safe_filename` 与 `safe_download_path`，不可自行用短随机文件名发布下载。若需要跨设备或长时下载，应升级为带审计记录的数据库授权/对象存储短签名 URL，而不是放宽 session 校验。若 Gallery 部署为多实例，BFF 本地桶不能替代 Generation Service 的全局限制。

## 更新（2026-08-09）：CSP 改为 per-request nonce

初版将 Gallery CSP 静态设置为 `default-src 'self'`，会拦截 Next.js App Router
流式渲染用于揭示正文的内联脚本（`$RS` 等），导致 `/gallery` 只显示头部与加载骨架，
正文永远不出现；同时 `img-src` 也会拦截腾讯云 COS/CDN 作品图。

修复：由 `src/proxy.ts`（Next.js 16 Proxy）为每个请求生成随机 nonce，并把 CSP
写入请求与响应头；Next.js 自动把 nonce 应用到框架脚本、页面 JS 与内联脚本，
`style-src` 保留 `'unsafe-inline'`（组件使用 React 内联样式），`img-src` 放开
`https:`（Generation Service 已按 `GALLERY_ASSET_HOSTS` 白名单校验所有资源 URL，
浏览器拿到的 URL 不可能来自未允许的存储/CDN 主机）。

## Performance

附件属主查询为带 owner 条件的单次数据库查询；ZIP 限制发生在解压前，避免内存和 CPU 放大。BFF 节流为 O(1) 内存访问，定期清除过期桶。

## Cost

本阶段复用现有 Flask session、PostgreSQL 附件记录和 Generation Service；未新增 Redis、数据库表、SaaS 或基础设施费用。

## Security

覆盖 CSRF、IDOR、路径/通配读取、ZIP 炸弹、点击劫持、缺失 Origin 放行、BFF 越权、错误信息泄漏和可猜测下载 URL。上传文件仍受既有类型与大小限制，生产发布前需在 staging 验证 CSP 不影响所需第三方资源。

## Rollback Plan

代码回滚可恢复旧行为，但不得作为常规故障处理。若 CSP 造成页面资源失败，可仅回滚 CSP header，同时保留 `frame-ancestors`、CSRF、属主检查和 BFF 授权。若下载 session 绑定影响合法流程，优先排查未使用 `safe_filename` 的新工具；仅在修复调用点后发布，不取消访问控制。
