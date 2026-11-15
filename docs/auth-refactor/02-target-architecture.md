# 02 目标架构（已批准分阶段实施）

2026-11-14：用户批准进入 Phase 1，并明确新微信账号注册后立即获得发票助手权限；仅自动授予 reimbursement，不扩展其他业务权限。架构仍是目标状态，不表示全部实现。

## 1. 推荐与设计门禁

保留 Flask 为统一认证权威，`users` 直接承担 Account，`account_id = users.id`。Account 是领域名称，不要求改表名。现有角色、套餐、工具授权、组织角色继续独立管理。

| 设计问题 | 结论 |
| --- | --- |
| 生产影响 | 认证跨网站、小程序、画廊，影响大；采用加法迁移、兼容版本先行、逐项开关与恢复演练 |
| 可复用性 | 账号、凭据、会话、邮件为平台能力；发票 grant 留在业务授权层 |
| 简单与成本 | 复用 Flask、PostgreSQL、现有 SMTP/限流；不新增认证微服务或短信服务 |
| 初学者维护 | 一个身份权威，一套迁移和运维入口；不引入额外认证平台的数据库、管理台和备份 |
| 架构适配 | 现有 public.users.id 已被 ai schema 外键引用，保留 ID 能显著降低历史数据迁移风险 |

不采用大型认证框架或本轮新增用户名/手机号。Sa-Token/uni-id/Logto 未选用，未安装；没有为选用它们而作维护/许可背书。新增密码建议 Argon2id，原有 Werkzeug scrypt/PBKDF2 按原算法验证，成功登录后再升级；安装前评估 Argon2id 参数与服务器内存并发，不批量改旧 hash。

## 2. 数据模型建议

| 模型 | 加法方案 |
| --- | --- |
| users / Account | 保持 id；新增 email_verified_at、auth_epoch（默认 0）、updated_at；保留 is_active_user 等原字段。完成兼容审计后才允许 email/password_hash 为空，以支持微信专用账号；不使用假邮箱/随机密码伪装身份 |
| account_external_identities / Identity | 扩展 identity_type、password_hash、updated_at、last_login_at、verified_at；subject 从 128 扩到 255；现 provider/client_id/subject/user_id/active 保持。web_password 使用固定非空 client_id=web、规范化邮箱 subject；openid 三元唯一性不变 |
| 旧 website_password 行 | 标记为 legacy_mobile_password 类型，不作为网站密码权威，不改 subject 或行 ID，以保留现存移动会话 |
| 网站会话 account_web_sessions | 新表：随机 session id 摘要、user_id、epoch、expiry、revoked_at、认证时间；Cookie/Remember 只携带签名的会话引用，不存密码 |
| 移动会话 | 保留旧表、token 摘要及 TTL；新增 epoch、认证时间/方式，新增列兼容回填；本期可继续 24h/7d，不为重构硬加 refresh token |
| account_action_tokens | 新表：purpose、user_id/目标邮箱引用、token_hash 唯一、expires_at、consumed_at、credential/epoch 版本；邮箱验证/重置/敏感操作使用，不能跨用途兑换 |
| 绑定挑战 | 扩展现表为 prepare→confirm→consumed/expired 状态，绑定来源会话、两端身份与重认证时间；旧挑战限时过渡，不重复造第二套绑定权威 |
| 认证邮件任务 | 新的轻量任务表：用途、account/目标地址引用、幂等键、状态、尝试次数、下次重试、错误码；不得放原始 token 或完整链接 |
| 认证审计 / 迁移记录 | 通用 account_auth_audits、auth_migration_runs 与逐账号映射/异常清单；保留旧 mobile_audits；合并若将来开放，独立 merge_operation/迁移清单保存来源和目标，不删除来源账号 |

此为候选表设计，Phase 1 先补索引/约束/容量与生产 schema 预检，再落 Migration。唯一邮箱使用与旧登录一致的 strip+lower；不擅自做 Gmail 去点/去加号合并。规范化碰撞必须报错，不覆盖。

为防双重权威：过渡阶段所有密码修改、管理员重置、注册都走统一服务，在同一事务同步 Identity 与 legacy users.password_hash；保留 legacy hash 只为旧读者兼容。回填与增量双写对账后才切换身份表为权威。所有读取者先支持新 hash，才开启升级。最终旧凭据字段只读保留；users 主表继续活跃，不因“旧表归档”要求而归档仍在使用的账号主表。

## 3. 统一服务与会话边界

在 auth 包中建立账号/凭据/会话/动作凭证/绑定服务，现路由充当适配层。登录成功输出内部 Principal(account_id, auth_method, session_id)，对外保留现有 access_token/expires_at/display_name/auth_method/userId 字段。

网站继续 Cookie+CSRF，小程序继续 Bearer 且拒绝 Cookie，画廊继续服务端 introspection；“统一”是同一个账号和状态校验，不是互换 token。微信 AppSecret 永远只在服务端。

会话撤销方案：

1. 新登录创建服务端会话，检查 active 与 epoch；注销撤销当前会话，退出所有设备、密码重置、禁用、身份转移递增 auth_epoch 并撤销所有端会话。
2. Flask-Login session/remember 的认证标识需要包含版本/会话引用；旧数字 user ID 经兼容解析。不能把新的复合标识直接传给 `int(current_user.get_id())`：Gallery 桥需改用已验证的 `current_user.id`。
3. 旧无版本 Cookie/Remember 仅在 account epoch=0 且兼容窗口未截止时接受；发生重置/撤销后禁止用旧 Cookie 升级为新会话。旧 Cookie 的注销无法准确指认单条会话，采用递增账号 epoch 的保守策略，并在退出说明中告知影响其他旧会话。
4. 旧移动 Token 哈希与身份引用保留；按账号 epoch 规则加入校验。旧没有 epoch 的会话仅当账号 epoch=0 接受，不能默认填成当前 epoch 复活已撤销凭据。
5. Remember、Cookie Secure/SameSite/HttpOnly、会话 TTL 和代理来源统一配置；旧签名 SECRET_KEY 不随迁移无故轮换。
6. BFF 每请求 introspection、不跨用户缓存。Generation 高风险写操作对账号状态/epoch 再校验；内部 HMAC 即使未过期也不能绕过撤销。现 internal payload v1 保留兼容，v2 字段与上线顺序专门测试。

## 4. 双端注册与授权

- 网站沿用邮箱+密码。新邮箱验证凭证独立生成，未验证账号不能使用邮件找回；旧用户仍可原密码登录。无邮箱/未验证旧用户在登录后补充邮箱并证明控制权，不默认已验证。
- 小程序通过 wx.login→后端 jscode2session，成功且合法 openid 后，在事务内查唯一身份；不存在才创建 users 与微信 Identity。并发唯一冲突整体回滚并重新读取，不能留下孤立 User。微信服务失败绝不创建账号。
- 登录/注册/账号信息/绑定/退出从发票 grant 中分离；未获业务授权也能管理自己的账号。
- **已确认的产品权限点**：新微信账号注册事务内自动授予 reimbursement，注册后立即可用；其余私有工具/CRM/管理员权限不授予。现有账号及既有授权不因登录或绑定自动扩大。独立注册入口和授权事务在 Phase 4 实现。

## 5. 双向绑定、合并与解绑

### 网站先注册

网站重认证创建一次性短时挑战，绑定发起会话。小程序新鲜 wx code 验证微信控制权，prepare 返回脱敏账号和影响摘要。用户确认后，事务重新检查两端状态、epoch、会话、挑战时效和身份归属，原子消费并绑定。网站会话在确认时已退出/被撤销则挑战失效。

### 小程序先注册 / 双账号

小程序提供当前有效会话+新鲜微信证明，输入网站凭据仅用于验证目标控制权；prepare 不切换当前账号。confirm 必须引用服务器的一次性交易凭证和用户确认，不接受客户端任意 target_account_id。

- 同一账号重复绑定幂等返回。
- 微信属于第三账号、任一账号禁用、会话失效、角色/付费资产冲突时拒绝，不覆盖。
- 若来源账号仅有这次自动创建的身份/会话，无授权、无计量和任何业务数据，经完整预检可迁移此身份到目标；来源账号保留为不可登录的迁移记录，旧会话全部撤销，返回新目标会话。
- **有业务数据的两个账号，首版阻止自动合并，显示申请人工处理入口与不含敏感内容的追踪号**。人工处理也不得手工执行简单 UPDATE：必须生成逐表预检、冲突决定、审计和恢复清单，经备份恢复演练再执行。Phase 5 若需自动合并，另行审批专项设计。
- 不因邮箱相同合并；角色、grant、积分、订单不自动并集。详细冲突见迁移文档。

解绑需近期重认证，并在同一账号锁下检查解绑后至少有一种可用身份（微信身份仍活跃且可访问，或有效密码身份；可信找回邮箱不能单独算密码登录）。两个并发解绑不能同时删掉最后身份；保留历史记录与业务数据。旧解绑 routes 由统一服务处理。

## 6. 邮箱验证与密码找回

1. 请求重置前先检查全局发信配置。未配置时对所有邮箱返回一致“邮件找回暂不可用”，运维能看到缺失配置；不能返回“邮件已发送”。
2. 配置正常后，无论账号存在/邮箱已验证/发送是否成功，公开响应一致“若该邮箱符合找回条件，将收到邮件”；异步投递状态不对外泄露。IP、邮箱摘要、设备/会话标识联合限流，设备只是辅助维度。
3. Worker 从任务取符合资格的账号，生成 secrets.token_urlsafe(32)；数据库仅存 SHA256 摘要，30 分钟到期。原始 token 仅在进程内用于邮件构造；不写通用 CRM outbox 模板数据、不记录日志。
4. 重试在内存中可复用；进程重启后生成新 token 并使旧尝试失效，投递回执未知也不把旧 token 内容持久化。邮件需说明以最近链接为准；达到次数上限仅记录安全错误码。
5. 重置 GET 不能消费 token。落地页先设置 no-store、Referrer-Policy:no-referrer、严格 CSP/禁第三方资源；入口代理日志须屏蔽敏感参数。浏览器立即 history.replaceState 清除 token，token 存于短期表单内存/受限服务端流程，不放 LocalStorage。
6. POST 校验新密码、用途、时效、用户状态、凭据版本；使用条件 UPDATE/RETURNING 原子消费（仅 consumed_at IS NULL 且未过期），与密码写入、epoch 递增、全端会话撤销、审计同事务。失败回滚不能烧掉 token。
7. 邮箱变更验证的是具体规范化地址，不是单纯用户 ID；重置目标必须仍为已验证邮箱。旧未验证用户可继续登录，但不能凭邮箱字段直接找回。

保留管理员辅助恢复入口作为过渡，但重置后也必须走统一撤销和审计；旧签名码过渡兑换需稳定摘要登记防并发消费。以后停用应提前公告，不突然废弃旧 API。

## 7. 邮件方案与成本核验

优先抽取现有 SMTP 传输为通用 `shared/mail.py`，提供 smtp/capture/disabled，保留 CRM 适配调用；认证发信不受 CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED 控制。不把带凭证邮件塞进当前绑定组织的 CRM outbox。

2026-11-14 官方资料核验：Resend [定价页](https://resend.com/pricing) Free 有 100/day 限制及 SMTP/API；[免费层公告](https://resend.com/blog/new-free-tier)列出 3,000/month。部署时仍须再次核对账户实际额度、发信域验证、条款和费用，不承诺永久免费。Gmail [应用密码条件](https://support.google.com/accounts/answer/185833)要求开启两步验证且部分账户不可用，[客户端说明](https://support.google.com/mail/answer/7126229)不再支持普通账号密码式第三方登录，因此不把个人 Gmail 当默认生产方案。

大陆服务器到供应商的连接、SMTP 端口、SPF/DKIM/DMARC、收件箱送达和配额均尚未实测；本轮不开户、不发信、不启用付费服务。选用已有可达 SMTP 成本最低，Resend 是候选，未决定迁移供应商。开发 capture 输出只进入受限测试存储，不进入普通生产日志。

## 8. 预计改动文件与阶段边界

| 阶段 | 预计文件/内容 |
| --- | --- |
| 1 | models.py、auth/mobile_models.py、独立 migrations/versions、拟新增 scripts/ops/auth_migration.py；只加结构/兼容/对账与隔离测试 |
| 2 | auth 下 account/identity/session/action-token/audit 服务、app.py user_loader、auth/routes.py、mobile_service.py、mobile_routes.py、admin/routes.py；适配旧契约 |
| 3 | auth/forms.py、templates/login/register/forgot/profile、新 reset/verify/security 模板、shared/mail.py、shared/notifications.py、config.py、.env.example；前后端完整流程 |
| 4 | apps/invoice-miniprogram/lib/api.js、auth.js、mine 页面及账号设置页面/app.json；与现有 UI 分支协调 |
| 5 | auth/tool_access.py、decorators.py；各业务仅按证据修正主体获取，不能无授权改业务规则；Gallery viewer/introspection/client、Generation internal-auth 和写操作安全检查 |
| 6 | tests/test_auth_*、现 mobile/gallery/CRM/权限测试、PG 并发、跨端 E2E；.github/workflows/ci.yml、部署与恢复文档 |

估计是 6 个分阶段交付、约 20–30 个工作日量级，取决于历史异常、邮件可达性和真实两端验收，不是 UI 小改动。每阶段先报告结果/风险再推进；Phase 0 完成后必须等待用户确认。

后续按用户清单补 05–09 文档，本轮不建立空的“完成报告”。新功能/部署开关默认关闭，明确以最低兼容版本为回退底线；微信无邮箱账号启用后，不得直接回退到假定 email/hash 非空的旧代码。
