# 07 认证重构测试报告

更新：2026-11-15。本报告区分历史阶段与当前发布候选结果，不代表真实生产验收。

## 邮箱验证注册闭环（2026-11-16）

本地完整回归449项，385通过、64跳过、0失败，284.220秒。新增HTTPS完整注册/欢迎/登录/找回闭环、未验证不创建User或session、邮箱冲突与预注册保护、过期/重发/重放、欢迎失败重试、旧邮件任务和业务迁移保持。之后另执行8项相关迁移/HTTPS/运维harness通过，与全量重叠不相加。

新PG16注册用例9项包含实际发布器迁移、注入摘要不符事务回滚及重试、并发请求只产生一项申请/任务、并发确认只有一位成功等；当前本地跳过，已配置CI。真实恢复库的新版迁移与全流程验收尚待执行。旧网站注册自动登录的测试已按新产品合同改为验证后显式登录，保持Gallery安全回跳和权限检查。

## 专用发件身份（2026-11-16）

`tests.test_auth_mail_sender tests.test_auth_email_https tests.test_customer_project_reminders tests.test_auth_release` 24项通过。新增SMTP mock验证账号邮件From与随后项目提醒From独立、不修改全局配置；未配置兼容旧地址，非法独立地址拒绝就绪并禁止连接。操作员已确认原发件身份的验证和重置邮件实际收到；新 accounts 发件身份尚未在服务商开通，不能标记专用地址已投递通过。

## HTTPS 邮件表单热修复（2026-11-16）

生产真实浏览器发现 no-referrer 策略与 Flask-WTF HTTPS严格来源校验冲突，导致提交返回400。账号响应和邮件落地页meta统一改为same-origin，跨站不发送来源，令牌仍只放fragment；保留CSRF和严格来源校验。

`tests.test_auth_email_https tests.test_auth_release` 共12项通过。新增开启CSRF和HTTPS的真实模板测试，覆盖网站登录→邮箱验证→申请重置→设置新密码→旧会话失效，缺token/跨站来源/无来源仍拒绝。此前模拟验收关闭CSRF，未覆盖此生产浏览器合同；本次补齐。无数据库迁移。

## 当前 Phase 1–6 发布候选

| 检查 | 结果 |
| --- | --- |
| Python 全量 `unittest discover -s tests -t . -p 'test_*.py'` | 423 项，369 通过，54 skipped，0 失败，295.679 秒 |
| 新增演练 CLI 保护 + 邮件/微信回归 | 12/12 通过，其中 10 项与全量重叠，2 项为之后新增 |
| Generation 完整 Node 测试 | 108/108 通过 |
| Gallery Node 测试 | 21/21 通过 |
| Generation / Gallery TypeScript | 两者通过 |
| Gallery Next 生产构建 | 通过 |

新增覆盖邮箱验证/过期/一次性消费、重置撤销、失败重试、GET不消费、微信注册即发票权限、重复注册、设置网站密码保留ID、绑定来源会话撤销和冲突拒绝。退出相关旧测试已改为 POST；GET继续显示确认，不执行退出。普通客户权限、网站/小程序字段一致、Excel、历史原件和用户隔离回归通过。

54 个跳过包括需要数据库或外部环境的既有测试；其中认证 PG 测试13个未在本地执行。随后远端 [CI 43731094179](https://github.com/shilei2024/my-toolbox/actions/runs/43731094179) 的三组认证检查全部通过，覆盖并发回填/重置/注册、令牌竞争和生产发布器实际三阶段迁移。该轮旧移动迁移测试有2个夹具失败：最新版 create_all 加入了新的映射外键，旧 f5 降级演练未移除该空表；已修正隔离夹具，正在重跑整个门禁。没有修改生产迁移以绕过约束。

最终代码候选 `553bd4476cef870c487620846ba199a7992d1f87` 的 [CI 43731683573](https://github.com/shilei2024/my-toolbox/actions/runs/43731683573) 五项全部成功：Python tests、Mobile invoice PostgreSQL 16、PostgreSQL integration、Generation Service、Gallery Web。上述旧迁移夹具问题已解决；保留历史发布器对新 head 的拒绝保护，在测试中冻结旧迁移树完成原合同演练。此后本次收尾只更新验收文档，没有改变受测业务代码。

**未完成的外部验收**：真实恢复库对账、实际 SMTP 收件、微信体验版和生产域名完整 E2E，以及代码审查/合并。当前为可提交审查的发布候选，不能越过这些门禁直接部署。

以下保留历史阶段记录，数字不与当前全量叠加。

## 本地已执行

```text
python -m unittest tests.test_auth_identity_phase1 tests.test_mobile_invoice_migration tests.test_password_reset tests.test_mobile_password_login tests.test_mobile_invoice_upload tests.test_gallery_auth_bridge tests.test_invoice_customer_access
Ran 54 tests ... OK
```

54/54 通过。新增 12 项覆盖：只读预检、恒等映射/重复回填、旧密码原字节复制、邮箱碰撞、停用匿名化账号、资料不完整与未知 hash、凭据漂移、注入失败整事务回滚、无数据 schema downgrade/有数据拒绝删除、唯一身份约束、会话归属冲突、旧数字 ID 解析，以及隔离 CLI 升级/备份摘要/恢复。

随后加强真实迁移后旧网站 Cookie、微信 Bearer 和旧移动密码 Bearer 的兼容验证，12 项再次通过。补充的 SQLite 备份文件恢复至另一临时库验证单独通过；不重复计入 54 项总数。

原件 BLOB、发票 ownership、用户密码/角色/套餐/配额、既有微信及 password-session 身份、会话 token_hash/时效、绑定挑战和工具授权均比较前后快照不变。没有新增或改写真实用户。

`git diff --check` 通过。仅有 Windows 行尾转换提示，不属于测试失败。

## PostgreSQL

新增 `tests.test_auth_identity_postgres` 3 项：双线程并发回填、事务回滚重试、真实 PG CHECK/结构恢复。当前本地没有配置专用 PostgreSQL，结果为 **skipped=3**，未视为通过。已接入 CI 的 PostgreSQL16 job，本轮未取得远端运行结果。

## Phase 1 当时未执行 / 未实现

- 真实生产备份恢复、用户总量与异常统计、全业务表逐用户对账；仍无恢复库。
- 邮箱验证/真实发信/新密码重置；属于后续阶段。
- 微信独立注册及注册即获得发票权限；规则已批准，接口将在后续阶段实施。
- 双端 prepare/confirm 绑定、安全合并、新全端 session 撤销、浏览器与微信真机 E2E。

因此 Phase 1 实现与 SQLite 验证可供审查，**PG 验收和真实迁移前置条件尚未满足；不符合生产部署条件**。


## Phase 2 本地验证（2026-11-14）

执行：

```text
python -m unittest tests.test_auth_service_phase2 tests.test_auth_service_postgres tests.test_auth_identity_phase1 tests.test_auth_identity_postgres tests.test_mobile_invoice_migration tests.test_password_reset tests.test_mobile_password_login tests.test_mobile_invoice_upload tests.test_gallery_auth_bridge tests.test_invoice_customer_access
Ran 70 tests in 67.281s
OK (skipped=5)
```

主回归65项通过，5项PG测试因无专用数据库跳过（不是通过）。之后补充真实退出模板/CSRF验证、隔离CLI Phase 2 upgrade-auth和重复执行验证，再执行：

```text
python -m unittest tests.test_auth_service_phase2 tests.test_auth_identity_phase1 -v
Ran 24 tests in 4.962s
OK
```

当前新增Phase 2本地测试共12项；第二次运行与主回归重叠，不能相加为89项。总计覆盖66个不同的通过用例，5个PG用例未运行。覆盖：真实Cookie/Remember恢复及退出重放、Gallery数值ID、注册身份镜像且无私有授权、统一失败响应与脱敏审计、双移动渠道/绑定挑战全端重置、禁用再启用、旧Cookie窗口、到期/非法标识、失败事务回滚、软删除、迁移空回退/有数据拒绝删除，以及退出确认与CSRF。

PG新增两项：同一恢复码并发兑换只有一个成功；旧密码登录与重置并发不遗留有效旧会话。与Phase 1三项合计五项，已配置在CI的PG16任务，但没有本轮远端执行证据。

限制：没有真实生产恢复库、真机微信或完整浏览器预发布；原件/业务归属通过合成数据回归验证。Flask-Login有既有datetime.utcnow弃用提示，不影响当前通过结果。尚未发信、开放微信独立注册或执行真实数据迁移。不能据此认定可直接生产上线。
