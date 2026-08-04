# ADR-0008：Generation Service 管理控制面、双层 RBAC 与乐观并发

状态：Accepted  
阶段：Phase 8

## Why

内容审核、Provider 状态和 Workflow 可用性会直接影响公开内容与生成路由，不能由浏览器或 Next.js 单独决定。选择在 Generation Service 内建立 AdminService 与事务仓储，Next.js 只提供 SSR/BFF 管理界面。Next layout 做体验层角色过滤，业务服务再次验证 HMAC Admin 身份。每个配置写入携带 `expectedUpdatedAt`，数据库锁定资源并执行乐观并发检查；审核状态、发布时点、moderation event 和 audit log 在同一事务提交。

## Alternatives Considered

- 复用现有 Flask Admin 直接写 `ai` schema：页面开发快，但把 AI 领域规则和事务重新耦合到旧站。
- Next.js 直连 PostgreSQL：减少 API 层代码，但扩大数据库暴露面，RBAC、审计和并发规则会分裂。
- 只依赖前端隐藏 Admin 导航：无法阻止直接 API 调用，不能作为授权机制。
- 使用 last-write-wins：实现简单，但多个管理员会静默覆盖审核或路由配置。
- 引入完整 RBAC 权限表：细粒度强，但当前只有 Admin/User/Guest 三类角色；过早增加角色、权限、继承和策略编辑成本。
- 后台直接管理 API key：方便运维，但会把密钥暴露给数据库读模型、BFF 和浏览器；继续使用外部 secret reference 发布流程。
- 直接在线编辑 Workflow JSON：灵活，但破坏不可变版本和可复现生成；后台只开关已发布版本。

## Future Impact

Phase 9 多 Provider 可以复用 Provider 列表、启停和优先级控制，但 Provider 创建、secret 发布与能力配置应通过受验证的 Adapter 发布流程扩展。Phase 10 可在相同控制面加入会员、积分异常和支付审计，但需要更细的权限与二次确认。管理员数量或职责分化后，可把 `requireAdmin` 升级为 permission claims，而不改变页面/BFF/Service 边界。批量审核需新增作业和幂等操作，不应循环调用单条 API。

## Performance

Dashboard 用六个并行、有限结果集的查询构建读模型；Provider/Workflow 数据量小，审核、任务和审计均有限制。`0003` 增加审核队列和最近审计索引。写入使用短事务、行级 `FOR UPDATE` 和时间戳比较；不会锁整表。管理员流量低，不单独增加 Redis 缓存，避免缓存敏感管理状态和失效复杂度。

## Cost

不新增服务、数据库或第三方后台平台。AdminService 与现有 Gallery API 同进程部署，共用 PostgreSQL、身份桥和日志。成本仅来自少量管理查询、两个索引和审计存储。签名缩略图直接由 COS 提供，应用不代理图片。保留手工审核而非引入新的付费 AI 审核 Provider，符合当前低成本阶段。

## Security

角色来自 Flask Session 内省并由 Next.js 以 60 秒 HMAC 上下文传递；Generation Service 独立要求 `role=admin`。BFF 拒绝跨 Origin 写入并限制 16 KiB 请求体；服务限制字段、枚举、数组数量、优先级范围和 UUID。Provider `secret_ref` 不返回，只暴露布尔状态；后台不返回 Prompt、audit metadata 或原始错误。所有变更写入审计，审核同时写 moderation event。乐观并发防止静默覆盖；管理页面和 API 禁止索引。

## Rollback Plan

先回滚 Next.js 以移除管理入口，再回滚 Generation Service。`0003` 只增加索引，默认保留；旧版服务可继续使用同一 schema。已提交的审核、Provider 和 Workflow 变更不随版本回滚，依据 audit log 执行新的补偿操作。若 Admin API 出现异常，可在反向代理立即封禁 `/v1/admin/*`，不影响 Generation、Gallery、SEO 或队列。若审核错误，保留期内可重新审核或撤销软删除；COS 已物理删除时按 Phase 6 备份策略恢复。
