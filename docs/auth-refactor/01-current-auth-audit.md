# 01 当前认证审计

日期：2026-11-14。阶段：Phase 0，仅代码审计，等待方案确认。

## 1. 范围与证据边界

- 基线：本地 `codex/invoice-mini-ui-simplify`，HEAD `d348061bc58c97a2ad25cc23af72c7c688dc7e60`，另有上一轮小程序 UI/Logo 未提交改动。本轮不修改这些改动或认证业务代码。
- 已阅读根 AGENTS、README、requirements、Flask 配置/模型/迁移/认证/授权、原生小程序、画廊身份桥、生成服务 SQL、部署指南、备份脚本与相关测试。
- 用户明确目前无生产备份恢复库，先完成代码审计。未连接生产数据库、未读取真实用户明细、未执行数据库迁移或发送邮件；历史对话中的 PG16 版本和 Alembic 版本不是本次实时核验。
- **用户数量、异常用户数量、真实密码算法分布、已绑定人数及业务行数均未知，不是 0。** 代码结构审计完成不等于真实数据迁移审计完成。
- 文档仅给出设计建议；Phase 1–6 未实施。下文引用均为仓库相对路径，可在当前基线复核。

## 2. 真实架构

| 层 | 实现与事实来源 |
| --- | --- |
| 网站与身份权威 | Flask 3.0.3，Flask-Login 0.6.3、Flask-WTF/CSRF、Flask-Limiter，Jinja/Bootstrap；`app.py`、`extensions.py`、`requirements.txt` |
| 数据 | SQLAlchemy 2、Flask-Migrate/Alembic；开发支持 SQLite，生产设计为 PostgreSQL；`models.py`、`shared/models.py`、域模型及 `migrations/` |
| 小程序 | 原生 JS/WXML/WXSS；`lib/api.js` 保存可过期 Bearer，`lib/auth.js` 同步页面登录状态；没有独立用户主表 |
| 画廊 | Next.js 16 / React 19 BFF；`src/server/viewer.ts` 转发 Flask Cookie，附服务端密钥调用 introspection |
| AI 后端 | Node 22、Fastify、PostgreSQL `ai` schema、BullMQ/Redis、COS；BFF 发带 HMAC 的用户上下文，`internal-auth.ts` 校验签名、时效与用户 ID |
| 部署 | 存在 Flask systemd/Gunicorn、Caddy、Generation Docker、Gallery Vercel 路径；README 的 Nginx 和旧部署指南中的 Flask Vercel 不能当成当前生产拓扑证明 |
| 邮件 | `shared/notifications.py` 已有 SMTP + dry-run + outbox/重试；模板、就绪检测、组织归属仍与 CRM 提醒耦合，不是现成的认证邮件服务 |

主站账号已经是大部分业务的唯一用户来源。建议保留此权威，不另建 Node 用户系统。

## 3. 当前用户与身份结构

### users（models.py: User）

| 字段 | 当前语义 | 迁移要求 |
| --- | --- | --- |
| id | Integer 主键 | 原值永久保留，作为逻辑 account_id |
| email | String(255)，唯一、非空、有索引 | 原始值不丢失；代码未记录是否验证；以后允许无邮箱账号，但不能伪造已验证状态 |
| password_hash | String(255)，非空 | 原样保留；Werkzeug generate/check；算法未显式固定，不是已实现 Argon2id |
| is_admin / is_active_user | 管理员与启停 | 原样保留，不能从微信注册推导管理员/工具权限 |
| nickname | 可空，80 字符 | 沿用显示名逻辑 |
| plan / custom_limits | 套餐、工具配额 JSON | 原样保留 |
| created_at / last_login_at | UTC naive 时间 | 不随回填重新生成 |

未发现 User 的用户名、手机号、email_verified_at、session/auth epoch 字段。无用户名登录入口，不应为了目标模型凭空引入。`admin/routes.py` 的旧软删除会停用并匿名化邮箱、将 hash 设为 `!`；此类账号必须保留，不得回填为可登录身份。

### 现有身份表（auth/mobile_models.py）

| 表 | 关键字段和约束 |
| --- | --- |
| account_external_identities | provider、client_id(AppID)、subject、nullable user_id、active；唯一 `(provider,client_id,subject)` |
| account_binding_challenges | user_id、provider、client_id、唯一 token_hash、expires_at、consumed_at |
| account_mobile_sessions | identity_id、user_id、唯一 token_hash、expires_at、revoked_at、created_at |
| account_mobile_audits | user_id、action、details_json、created_at；不依赖可删除的用户 FK |

`wechat_miniprogram` 身份 subject 是后端换取的 openid；`website_password` subject 是 `SHA256(user.id:password_hash)`，属于旧移动密码会话的校验身份，不是稳定邮箱身份。不能把二者当作相同凭据迁移。

## 4. 流程与接口清单

`app.py` 注册 auth_bp **没有 /auth 前缀**；部分单元测试自行挂在 /auth，不能据测试地址误写生产 API。

| 路径 / 方法 | 现状 |
| --- | --- |
| /register GET/POST | 邮箱小写化、密码 8–128 位且含字母数字、确认密码；直接创建 User，remember 自动登录；无邮箱验证 |
| /login GET/POST | 邮箱+密码；检查启停；支持 remember、安全 next 跳转；没有独立账号维度登录失败限流 |
| /logout GET/POST | logout_user 清除当前浏览器登录状态；无服务端网站 Session 记录 |
| /forgot GET/POST | 管理员重置码+邮箱+新密码；5/min POST；不是邮件找回 |
| /admin/users/<id>/password-reset POST | 管理员生成签名重置码，页面显示；非邮箱发送 |
| /profile GET/POST | 当前账号/昵称；昵称可同步 ai.user_profiles |
| /internal/gallery/session GET | Cookie introspection + 服务端共享密钥；返回 role/userId/email/nickname |
| /auth/internal/gallery/session GET | 上一接口的兼容别名 |
| /auth/mobile/challenge POST | 网站 fresh login+密码+发票权限，创建 10 分钟绑定码与二维码 |
| /auth/mobile/bindings GET | 查询当前 AppID 的有效绑定 |
| /auth/mobile/bindings/<id> DELETE | fresh login+密码；解绑并撤销该身份移动会话 |
| /api/mobile/session POST | wx code 在后端换 openid；可附 binding_code；未知身份返回 428，不自动注册 |
| /api/mobile/session/password POST | 网站邮箱密码换移动会话；必须拥有发票授权，非微信绑定；5/min IP、10/hour 规范化账号限流 |
| /api/mobile/logout POST | 撤销当前移动会话，有审计 |
| /api/mobile/bootstrap GET | 发票权限下取得用户名称、周期、客户等业务数据，不是通用账号中心 |

相关管理员账号变更入口：`/admin/users/<id>/toggle`、`/delete`、`/plan`、`/limit`、`/nickname`、`/credits`；未来须统一状态/凭据操作审计，不能漏掉管理员入口。

小程序 `mine/index.js` 扫码后直接调用登录绑定，缺少展示两个账号与明确确认的阶段；密码登录仅切换到网站身份，不将当前微信身份绑定过去。无独立注册、账号合并和通用安全设置。

## 5. Session / Token / 安全现状

- 网站使用 Flask 签名 Cookie，名 `mytoolbox_session`，HttpOnly、SameSite=Lax，永久会话默认 14 天。Secure 由环境决定，默认 False；生产配置未实时核验。Remember 使用 Flask-Login 机制，未见显式 remember 安全属性和独立撤销策略。
- User.get_id 继承默认数字字符串；user_loader 按 ID 取 User，没有密码版本/会话 ID 校验。密码变更不会令此前签名 Cookie 因凭据版本而失效，注销也没有服务端拒绝被复制旧 Cookie 的记录。
- **禁用检查不是缺失**：本地 Flask-Login 0.6.3 UserMixin.is_authenticated 返回 is_active，User 覆盖 is_active→is_active_user；移动认证另显式检查启停。仍须全入口回归及定义重新启用后旧会话是否恢复。
- 微信会话 token_urlsafe(32)，SHA256 存储，有效 7 天；移动密码会话 24 小时，无 refresh token。密码哈希变化使旧移动密码会话失效，**不会撤销微信会话**（现有测试明确断言这一行为）。
- 网站绑定码 token_urlsafe(24)，192 bit，10 分钟，只存摘要；数据库锁与身份唯一约束防冲突。旧码格式是 32 字符，不能直接延长而不兼容扫码客户端。
- 现重置码使用 itsdangerous 签名 uid+密码 hash 指纹，默认 60 分钟。先 verify 再 reset，无 token 消费表或原子条件更新；顺序重放会因 hash 改变失效，不能证明并发只成功一次。新密码仅检查至少 8 位，与注册强度不一致。
- CSRF 保护网站；mobile Blueprint 豁免但只接受 Bearer，拒绝 Cookie，不能反向授权网站路由。
- 全局默认 120/min/IP，存储默认 memory://；生产是否用了共享限流存储未知。ProxyFix 与代理层数需匹配真实入口。
- Gallery BFF 已信任服务端桥而非浏览器 userId，但 `viewer.ts` 成功日志含邮箱/昵称，需脱敏；内部签名上下文有时效，无逐请求统一 epoch 撤销校验。

## 6. 模块鉴权

| 模块 | 身份/权限边界 |
| --- | --- |
| 通用 PDF/图片/文本/转换工具 | `tools_config.yaml` + require_usage：匿名/用户配额；不能把统一身份误解为取消匿名功能 |
| FCST、发票助手 | `register_private_tool_guards` 根据配置前缀和 UserToolGrant 拦截；管理员旁路授权；owner_type/user + 字符串 user.id 隔离 |
| 发票打印工具 | 复用工具计量/当前用户，不新建用户主表；实际所有路由需 Phase 5 动态遍历回归 |
| CRM | `customer_projects/permissions.py`：feature/pilot、active organization membership、角色及项目成员范围；不是仅 login_required |
| 管理后台 | login_required/admin_required；不能在身份合并时并集提升管理员角色 |
| 小程序 API | service.authenticate + mobile_guard + reimbursement grant；账号服务与发票业务许可现在耦合 |
| 画廊、任务、积分、订单 | BFF→Flask introspection→HMAC 用户上下文；SQL 归属 public.users.id；无需独立注册 |

静态梳理不是所有路由均已通过动态越权验证。私有工具测试默认可能绕过 guard，未来必须开启 `ENFORCE_PRIVATE_TOOL_ACCESS_IN_TESTS`。

## 7. 已执行检查

运行现有 4 组测试：`test_password_reset`、`test_mobile_password_login`、`test_mobile_invoice_upload`、`test_gallery_auth_bridge`，**35/35 通过**（2026-11-14，58.326 秒）。测试使用独立 Flask/内存 SQLite 和 mock 微信；未启动生产 app factory，未触及业务数据库。通过仅证明旧功能基线，不代表新要求实现。

未执行：真实 PostgreSQL 并发、生产数据计数、邮件投递、微信真机、新认证 E2E、恢复演练。现有 CI 含 Python、Gallery、Generation、PG16 mobile 与 PG18 integration，下一阶段必须增加新认证门禁。

## 8. 结论

优先沿用 users.id，扩展现有身份模型和会话机制；补齐可信邮箱、自助找回、微信自动注册、双端确认绑定及全端撤销。存在业务数据的双账号自动合并暂不开放，先给明确人工冲突处理路径。详细文件清单见 [目标架构](02-target-architecture.md)，数据归属逐表清单见 [迁移计划](03-data-migration-plan.md)，发布阻断见 [风险登记](04-risk-register.md)。
