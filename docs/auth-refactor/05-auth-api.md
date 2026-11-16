# 统一认证契约（Phase 1–6）

## 服务层

`account_service` 是共享账号服务：规范化标识、密码校验、注册、身份查询、密码镜像、状态变更与撤销。`session_service` 负责两种传输的会话签发/退出及网站凭据解析。渠道适配器保留微信服务调用和原移动接口格式。

写操作的锁顺序：User → Identity → Session。除 start_web_session 在设置 Cookie 前提交外，服务函数由调用方提交完整事务。禁止在校验与签发之间提前提交。密码过渡权威仍是 users.password_hash；web_password 同事务镜像，旧移动 website_password 指纹身份保持原语义。

## HTTP 兼容

| 入口 | 认证/行为 |
| --- | --- |
| POST /register | 邮箱表单/CSRF；创建待验证申请并入队邮件，统一跳转待验证页；不创建User或网站会话 |
| POST /login | 既有表单/CSRF；错误密码/停用统一 401；IP 每分钟5次、邮箱摘要每小时10次 |
| GET /logout | 展示确认，不撤销 |
| POST /logout | CSRF；撤销当前新网站会话并删除 Cookie；旧数字会话退出撤销全端 |
| POST /forgot | 兼容管理员签名码；锁定账号后再次验证；改密码、镜像、epoch、全端撤销和审计一并提交 |
| POST /api/mobile/session | 微信服务端换码；注册开关开启时新账号同事务获得 reimbursement 授权 |
| POST /api/mobile/session/password | 同一密码校验服务；保持原 reimbursement 授权门禁及 JSON 格式 |
| POST /api/mobile/logout | 撤销当前移动会话，其他独立会话保留 |
| GET /internal/gallery/session | 仅内部共享密钥可调用；输出稳定 userId，以及新会话的 authEpoch 和不可兑换的 SHA256 sessionRef；不输出原始会话令牌 |

网站会话 `v2:<随机值>` 仅存在签名 Cookie/Remember 内；数据库只存 SHA256，随机值有256位熵。记住我会话14天，其余1天，固定到期不滑动延长。移动密码24小时，微信7天，Token格式不变。过期、撤销、账号停用或 epoch 不一致均拒绝。

网站 Flask-Login loader 与移动 Bearer request_loader 各自解析凭据；移动端禁止 Cookie。私有工具继续调用已有 can_access_private_tool，身份认证不授予额外角色。Phase 4 的新微信账号才在注册事务内授予 reimbursement。

## 审计与限制

通用 account_auth_audits 记录内部 user_id（失败时为空）、动作、渠道、时间，无邮箱、密码、Token、请求正文。原移动审计继续保留。账号禁用/启用/删除和密码重置递增 epoch；重新启用不能恢复旧会话。

密码继续兼容 Werkzeug 既有哈希；管理员恢复和改密沿用至少8位、最长128位策略，注册维持字母+数字规则。Argon2id 升级与有业务数据的双账号合并不在本次发布范围。

## Phase 3–6 新接口

2026-11-17：用户要求恢复惯用注册交互。e0版本/register提交邮箱、密码及确认密码，仅将单向密码摘要保存到待验证申请；新邮件链接/account/email/register-confirm不再设置密码，POST确认后创建正式User并发送欢迎邮件。重发保持摘要；重新提交密码失效旧链接。d9旧申请无摘要时仍可用原/register邮件页面完成。部署参见[密码前置注册更新](13-password-first-registration.md)。

网站注册自 d9 版本起采用[邮箱验证闭环](11-verified-registration.md)：POST /account/email/register 验证一次性token并设置密码后，同事务创建已验证User/密码身份、标记申请完成及入队欢迎邮件；随后跳转注册成功页，用户再登录。GET不激活。GET/POST /account/registration/pending 提供重发，IP/邮箱限流和一分钟冷却；过期申请可以重发。匿名提示不区分已注册与未注册。注册邮件不可用时/register返回503且不创建数据。旧用户和微信注册规则保持。具体升级须先迁移d9，见[注册发布指南](12-registration-release.md)。

| 入口 | 认证和事务边界 |
| --- | --- |
| GET/POST /account/security | Cookie + CSRF；发验证邮件、旧密码确认后改密/撤销所有会话 |
| GET/POST /account/recover | CSRF + IP/邮箱摘要限流；统一返回，不泄露账号是否存在；仅已验证邮箱可找回 |
| GET/POST /account/email/verify 或 reset | 邮件 fragment 令牌进入 POST；GET 不消费；SHA256 摘要、30分钟、用途/邮箱/epoch绑定、一次性原子消费 |
| GET /api/mobile/account | Bearer；返回本人账号资料与是否已设置网站密码 |
| POST /api/mobile/account/password | Bearer + 新鲜微信 code；无密码账号设置邮箱/密码；同一用户ID、冲突不合并；撤销旧会话后返回新会话 |
| POST /api/mobile/account/logout-all | Bearer；全端撤销 |
| POST /api/mobile/binding/prepare | 新鲜微信 code + 网站 binding_code；校验来源网站会话仍有效，返回脱敏目标与 confirmation |
| POST /api/mobile/binding/confirm | 再次新鲜微信 code + confirmation；校验同一微信、来源会话和 epoch，消费挑战并签发移动会话 |

注册开关开启后旧的直接 binding_code 登录被拒绝并要求更新客户端。微信身份已属于其他账号时不自动转移；最后一个可用登录身份不能解绑。微信账号允许 email/password_hash 为空，绝不制造虚假邮箱或共享密码。

Gallery BFF 把 authEpoch/sessionRef 放入签名 v2 内部上下文。Generation 开启 AUTH_ENFORCE_SESSION 后，在认证请求执行前查询同一 PostgreSQL 账号和网站会话；缺失、过期、撤销、epoch不一致或管理员角色被移除均拒绝。它不缓存失效凭据。原始 Cookie/Token 不跨服务传递。已开始执行的业务任务不因之后退出自动取消。

邮件队列按账号/用途/邮箱/epoch去重，发送前复查账号，失败最多重试3次；原始链接仅存在发送进程内存和收件人的邮件中。数据库保存任务状态与令牌摘要，不保存明文链接。运维命令见[发布手册](10-release-runbook.md)。
