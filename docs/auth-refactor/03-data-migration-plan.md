# 03 旧数据迁移与对账方案（未执行）

## 1. 不变量

1. users.id 不变，逻辑 account_id 等于原 ID；无需全表重编号或把 openid 当主键。
2. 不删除原用户、密码 hash、openid、业务记录或原件 BLOB。停用/软删除账户保持原状态。
3. 仅新增身份记录/必要列；老表保留。业务 ownership 字段先保持原格式，通过统一 Principal 取原 user.id。
4. 当前迁移人数：**未执行**；真实用户总量/异常量：**未知**。用户确认暂无恢复库，不推测生产统计。
5. 发生冲突时停止对应批次并记录；不得自动选择获胜账号或清空旧表。

## 2. 字段迁移映射

| 旧字段 | 目标 | 处理 |
| --- | --- | --- |
| users.id | Account.id / account_id | 恒等映射，映射清单记录 source_id=target_id |
| users.email | Account.email + web_password Identity.subject | 保留原始资料；按现登录 strip+lower 生成标识，先查规范化冲突；不凭字符串认为已验证 |
| users.password_hash | Identity.password_hash + 兼容旧字段 | 原字节复制，分别统计 scrypt/PBKDF2/其他前缀及 `!` 停用标记；未知算法停下评估，不用新随机 hash 覆盖 |
| users.nickname | Account display_name 的现有来源 | 保留，可空 |
| is_admin/is_active_user/plan/custom_limits | 同名字段 | 不推断、不提升、不重置 |
| created_at/last_login_at | 同名字段 | 保留 UTC 精度，不以迁移时间重写 |
| 无 email_verified_at | 新字段 NULL | 没有历史可信证据就保持未验证，旧密码仍可登录 |
| 微信 provider/client_id/subject | 同一 Identity 原值 | 行 ID、openid、AppID 三元组不变；不得补猜 AppID/unionid |
| 微信 inactive / user_id NULL | 保留原绑定历史 | 不作为可用登录身份，不自动重新绑定 |
| website_password 旧 subject | legacy_mobile_password 原 subject | 保留凭据指纹绑定，仅过渡会话使用；不转成新的 web_password 邮箱标识 |
| account_mobile_sessions | 原行 + epoch 兼容字段 | token_hash/expiry/revoked_at 不改，不能重新发明原始 token |
| account_binding_challenges | 原行 + 过渡版本信息 | 保留 32 字符旧码契约及 hash，10 分钟自然过期；不恢复已消费码 |
| Website Cookie / Remember | 兼容认证标识 | 无服务端明文 token 可搬；按 epoch=0、窗口规则兼容，发生密码重置立即禁用旧凭据 |
| 手机号/用户名 | 无现有主表列 | 不生成；若生产 schema 发现历史扩展列，先补映射再实施 |

## 3. 数据归属、间接引用与合并冲突

下方附录逐表列出静态发现的用户字段，包含没有 FK 的 owner 和审计字段。Phase 1 预检还必须与生产 pg_catalog / information_schema 比较，发现未纳入的表/外键/触发器立即停止。

| 数据域 | 关键冲突 | 对账/合并策略 |
| --- | --- | --- |
| user_tool_grants | user/tool 复合 PK | 原授权保持；不自动并集权限 |
| user_usage | user/tool/day 唯一 | 不在身份回填时重算；未来合并需明确求和与配额政策 |
| pn_mappings | owner_type/owner_id 与品号唯一 | 同品号不同映射需人工选择，不覆盖 |
| reimbursement_records | owner/period 唯一，data_json 包含业务记录 | 不仅更新外层 owner；保留 JSON 原样并对比摘要 |
| periods/categories/offices/product_lines | owner+名称/代码唯一，周期活动状态 | ID 恒等时全保持；未来合并需逐项重映射，不能默认同名等价 |
| invoices/attachments | period/category/customer FK、附件去重 owner+content_sha256 | 对比原件大小/摘要/引用；重复附件不是可直接删除数据的理由 |
| aux_details | owner/period/type 与 data_json | JSON 中客户/产品线/派车引用纳入检查，不能盲目字符串替换 |
| upload_receipts | user/idempotency_key 唯一 | 保留重试幂等语义；合并时不能冲突覆盖另一张发票 |
| CRM | organization membership、角色、客户所有者、项目成员、评论和审计 | 私有客户组织 UUID 由 user.id 派生，ID 不变则无需重建；未来合并需独立组织/客户范围迁移方案 |
| ai 用户资料/互动 | 一用户一资料、image/user 点赞收藏唯一 | 不凭相同用户资料合并；互动去重须保留来源清单 |
| ai 任务/图片/媒体 | 用户幂等键、原图/参考图/COS 资源、任务保留金额 | 只对账不搬移；任务运行中禁止账号合并 |
| ai 订单/订阅/双积分账本/兑换码 | provider customer、订单幂等键、账本余额、活动订阅唯一 | 不直接改 owner 或相加余额；需财务语义和不可变账本专项方案。首版人工处理 |
| 审计/通知/导出/导入 | actor/recipient 与 JSON 快照 | actor 是历史操作人，不能因合并重写成目标；通知接收人需确认可达与访问权 |

ID 保持方案下，表中历史归属字段与 BLOB 应当逐项不变，而非只比较总行数。匿名 owner 不是 user ID，必须独立分类，禁止把 anon_id 转成账号 ID。

## 4. 生产预检所需汇总（未取得）

仅输出计数/摘要和错误类别，异常明细留在受限服务器文件，不贴聊天或提交 Git：

- users 总数、active/admin/停用数；NULL/空邮箱数、无效邮箱数、strip+lower 碰撞组数；密码算法/停用标记/空值分布。
- 每 provider/AppID 的 identity 数、active/解绑数、孤儿 user_id、三元组重复；绝不输出 openid。
- 会话总数/有效数/过期数/撤销数及错误 identity-user 配对；挑战有效/已消费/孤儿数量。
- 每个 ownership 表按用户分组的记录数；owner_type=user 但 owner_id 不能映射 users 的数量；账号状态和授权保持数量。
- 原件 BLOB 数/字节数/内容摘要；JSON 快照摘要；AI 任务、订单、现金与会员积分余额、预留/账本对账结果。
- schema/Alembic/AI SQL migration 版本、备份校验和/恢复结果、当前应用 SHA；连接串和秘密不输出。

网站邮箱当前非空是模型声明，不代表历史数据库不存在漂移。只有获得恢复库的只读核验，才能填写真实数值和确认迁移工作量。

## 5. 执行顺序（Phase 1 确认后）

1. 固定发布 SHA，先整理本地 UI 与客户修复依赖，不能拿未提交工作树直接部署。发现运行版本/模型漂移先停止。
2. 使用现有 `scripts/ops/invoice_backup.py` 思路做整个共享 PG 数据库备份（public 与 ai），校验文件，恢复到隔离同主版本 PG。仅有备份文件没有恢复验证不算通过。
3. 在隔离库只读预检 schema、索引、计数、归属、完整性；原件摘要任务限速，避免生产长事务。生产需要维护窗或一致性快照/写入冻结，不能拿不同时刻的计数硬比较。
4. 新独立 Alembic revision 接在实际单 head 后。仓库当前静态 head 为 f5a6b7c8d9e0，首条 migration 依赖已存在 legacy 表，不能认为从空库 upgrade 就能重建全部旧表。AI SQL 迁移链单独核验。
5. 先部署理解新旧结构/密码算法/会话格式的兼容代码；新业务功能关闭。禁止旧 worker 继续只写 users.password_hash 导致身份副本漂移；采用维护窗切换全部认证写者或受控增量双写。
6. 加字段/表/索引，旧列暂不删除。按 user.id 分批锁定并回填，记录 run_id、游标、目标键和完整性摘要；唯一冲突、算法不支持、外键孤儿进入异常清单并终止该事务。DDL 与数据回填分阶段，单批原子，不承诺跨数百万行一笔事务。
7. 重跑相同批次先核对已存在内容，完全一致记 skipped；不使用 ON CONFLICT UPDATE 静默覆盖。先验再写，回填期间创建/改密并发纳入测试。
8. 核对源/目标 account 映射、hash、openid、权限、业务归属、BLOB 摘要、账本和序列。报告 scanned/inserted/skipped/conflicted/failed，数值与输入总数对得上。
9. PG 并发测试：首次微信注册、挑战消费、密码重置、最后身份解绑、双写改密竞争。旧 API/旧 Cookie/旧移动 Token + 网站/Gallery/微信真机回归。
10. 用户批准后逐项开启新注册、验证、找回、绑定；旧签名码/旧会话过渡截止时间以实际发布记录为准，不在本轮虚构日期。

## 6. 回退与失败恢复

- 回填失败：当前事务 rollback，保留之前成功批次及审计；重新预检后幂等重跑，不清旧表。
- 新功能未启用：回退到兼容基线代码并关开关，保留新增表；优先避免 downgrade 删除凭据/审计。
- 新微信无邮箱用户或 Argon2id 已产生后：旧版本可能无法处理，**禁止直接回退至重构前版本**；回退最低版本必须理解 nullable 账号、新哈希、新 epoch，即使新功能关闭仍能安全登录旧/新用户。
- 密码重置/会话撤销不能通过降版本复活旧登录凭据。回退测试必须复测旧 Cookie/Token 继续无效。
- 完整备份恢复是事故恢复而非日常回退：先停写，保存故障后的增量与审计，评估新订单/发票等损失与补偿，经批准后恢复到新库切换；恢复后按恢复点要求撤销可能复活的会话。
- 双账号数据合并未实施，不能把上述身份回填回退当作其回滚方案。

## 7. 阶段准入

代码方案确认后可开发迁移与内存/隔离合成数据测试；任何真实旧数据迁移必须补齐恢复库、对账、备份恢复演练。最终 09-user-migration-report 在实际演练后生成，本轮不伪造人数或“零异常”。

## 附录：静态归属字段清单

以下清单由当前源文件语法/SQL 提取，不执行 app factory 或数据库查询。

### Python 模型

| 表 | 字段 | 源文件 |
| --- | --- | --- |
| user_tool_grants | user_id, granted_by_id | `models.py` |
| user_usage | user_id | `models.py` |
| usage_logs | user_id | `models.py` |
| pn_mappings | owner_type, owner_id | `models.py` |
| reimbursement_records | owner_type, owner_id | `models.py` |
| reimbursement_periods | owner_type, owner_id | `models.py` |
| reimbursement_categories | owner_type, owner_id | `models.py` |
| reimbursement_offices | owner_type, owner_id | `models.py` |
| reimbursement_product_lines | owner_type, owner_id | `models.py` |
| reimbursement_invoices | owner_type, owner_id | `models.py` |
| reimbursement_attachments | owner_type, owner_id | `models.py` |
| reimbursement_aux_details | owner_type, owner_id | `models.py` |
| account_external_identities | user_id | `auth/mobile_models.py` |
| account_binding_challenges | user_id | `auth/mobile_models.py` |
| account_mobile_sessions | user_id | `auth/mobile_models.py` |
| account_mobile_audits | user_id | `auth/mobile_models.py` |
| organization_memberships | user_id | `shared/models.py` |
| organization_business_day_overrides | created_by_user_id, updated_by_user_id | `shared/models.py` |
| audit_events | actor_user_id | `shared/models.py` |
| notification_deliveries | recipient_user_id | `shared/models.py` |
| project_saved_views | created_by_user_id | `customer_projects/models.py` |
| project_import_batches | created_by_user_id | `customer_projects/models.py` |
| customers | primary_owner_user_id, created_by_user_id, updated_by_user_id, deleted_by_user_id | `customer_projects/models.py` |
| customer_contacts | created_by_user_id, updated_by_user_id, deleted_by_user_id | `customer_projects/models.py` |
| customer_projects | primary_sales_user_id, created_by_user_id, updated_by_user_id, deleted_by_user_id | `customer_projects/models.py` |
| project_members | user_id | `customer_projects/models.py` |
| project_materials | price_updated_by_user_id, created_by_user_id, updated_by_user_id, deleted_by_user_id | `customer_projects/models.py` |
| material_competitors | created_by_user_id, updated_by_user_id, deleted_by_user_id | `customer_projects/models.py` |
| project_activities | created_by_user_id | `customer_projects/models.py` |
| project_comments | created_by_user_id | `customer_projects/models.py` |
| project_comment_mentions | user_id | `customer_projects/models.py` |
| project_stage_events | actor_user_id, approved_by_user_id | `customer_projects/models.py` |
| reimbursement_audits | owner_type, owner_id | `tools/reimbursement/models.py` |
| reimbursement_upload_receipts | user_id | `tools/reimbursement/mobile_models.py` |

### AI schema（SQL 迁移）

| 表 | 用户字段 | 来源 |
| --- | --- | --- |
| ai.workflows | created_by_user_id | `0001_initial.sql` |
| ai.workflow_versions | created_by_user_id | `0001_initial.sql` |
| ai.generation_jobs | user_id | `0001_initial.sql` |
| ai.images | creator_user_id | `0001_initial.sql` |
| ai.likes | user_id | `0001_initial.sql` |
| ai.favorites | user_id | `0001_initial.sql` |
| ai.comments | user_id | `0001_initial.sql` |
| ai.download_logs | user_id | `0001_initial.sql` |
| ai.moderation_events | reviewer_user_id | `0001_initial.sql` |
| ai.audit_logs | actor_user_id | `0001_initial.sql` |
| ai.system_settings | updated_by_user_id | `0001_initial.sql` |
| ai.user_profiles | user_id | `0002_gallery_system.sql` |
| ai.billing_customers | user_id | `0005_billing_credits_memberships.sql` |
| ai.payment_orders | user_id | `0005_billing_credits_memberships.sql` |
| ai.subscriptions | user_id | `0005_billing_credits_memberships.sql` |
| ai.credit_accounts | user_id | `0005_billing_credits_memberships.sql` |
| ai.credit_ledger_entries | user_id | `0005_billing_credits_memberships.sql` |
| ai.credit_reservations | user_id | `0005_billing_credits_memberships.sql` |
| ai.member_credit_accounts | user_id | `0010_member_credits_redemption.sql` |
| ai.redemption_codes | created_by | `0010_member_credits_redemption.sql` |
| ai.redemption_codes | redeemed_by | `0010_member_credits_redemption.sql` |
| ai.images | curated_by_user_id | `0025_curated_gallery.sql` |
