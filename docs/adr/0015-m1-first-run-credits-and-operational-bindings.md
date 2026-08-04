# ADR 0015：M1 首次积分、远端 Provider 绑定与发布策略

## Why

M1 主链路（创建 → 队列 → Provider → COS → Gallery）代码完成后仍无法开箱使用：新注册用户没有任何积分来源；OpenAI/Gemini/即梦 没有 workflow binding；新图片永远停留在 `pending`，公共画廊在人工审核前始终为空；Gallery Web 也没有登录入口。

## Decision

1. `BILLING_SIGNUP_GRANT`（默认 10，`0` 关闭）由 Billing Service 在用户首次调用账户汇总时幂等发放，写入 `ai.credit_ledger_entries`（`signup_grant`）。重复调用不重复发放，靠 `(user_id, idempotency_key)` 唯一约束保证。
2. 新增迁移 `0007_remote_provider_bindings.sql`：为每个活跃 workflow 增加 OpenAI / Gemini / 即梦 的默认模型绑定。Provider 行保持 `disabled`，管理员启用后 Selection Policy 才能路由。
3. `GALLERY_DEFAULT_MODERATION=pending|approved`（默认 `pending`）控制 Worker 落库时的新图片审核状态；`approved` 且公开时同步写入 `published_at`，直接进入公共画廊与 SEO。
4. Gallery Web 新增 `/login`、`/logout`、`/api/me/session` 与导航头会话状态；`MAVIS_AUTH_LOGIN_URL` / `MAVIS_AUTH_LOGOUT_URL` 指向 Flask，未配置时隐藏入口。

## Alternatives Considered

- 管理员手工 SQL 授权积分/绑定：拒绝，违背小白优先部署，且无审计。
- 注册时在 Flask 侧发积分：拒绝，会把计费写逻辑分散到认证模块，破坏统一账本边界。
- 默认自动审核所有图片：拒绝，生产合规风险；改为默认 `pending`，仅允许显式开启 `approved`。
- Gallery Web 自建登录页：拒绝，会复制 Flask 的密码/会话逻辑；保留同父域共享 Cookie 与跳转。

## Future Impact

积分发放未来可迁移到系统级配置或注册事件；Provider binding 可被管理后台的“新增绑定”能力替代；审核策略可为后续自动内容审核模块预留开关位。

## Performance

幂等发放是单行 `INSERT ... ON CONFLICT DO NOTHING` 加账本唯一约束，首次汇总额外一次写操作，后续调用无额外开销。

## Cost

无新增基础设施。默认 10 积分需要运营者按真实 Provider 单价评估；`0` 可关闭。`0007` 只增加目录行，不产生存储成本。

## Security

积分金额只接受服务端正则校验的非负 4 位小数；发放只以服务端用户身份为凭据，浏览器不可指定金额。审核与发布策略由服务端强制执行，`approved` 模式在生产需显式配置并配合审核制度。

## Rollback Plan

将 `BILLING_SIGNUP_GRANT=0` 并重启 API 即停止新发放（已发放余额保留）；禁用对应 Provider/Workflow 即撤回远端绑定；恢复 `GALLERY_DEFAULT_MODERATION=pending` 并重启 Worker 即回到人工审核；移除 Vercel 的登录 URL 变量即隐藏入口。`0007` 无需删除，任何环境均可安全保留。
