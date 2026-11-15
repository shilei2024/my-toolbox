# Phase 1：数据库扩展与旧身份兼容

日期：2026-11-14。状态：实现与 SQLite 隔离验收完成；PostgreSQL 验收待运行，不可生产部署。

## 已确认的产品规则

用户已批准 Phase 0 方案，并明确：**小程序新用户注册成功后立即可以使用发票助手**。后续微信独立注册事务须原子创建 User、微信 Identity 和唯一的 `reimbursement` UserToolGrant；不得授予 admin、FCST、CRM 或其他工具，也不得利用绑定/重试重复发放权益。grant 由系统发放，granted_by_id 可为空。登录已有账号不应无条件追加授权；老用户授权保持原状。实际自动注册入口属于 Phase 4，本阶段不冒充已上线。

## 设计门禁与本期边界

- 生产：模型增加列必须先迁移再运行新应用；本轮未部署。独立 migration 不触碰历史业务所有者。
- 复用：账户 ID 适配、身份回填、运行审计属于 auth 通用能力。
- 成本：复用 SQLAlchemy/Alembic/PG，不新增服务或依赖。
- 维护：独立 CLI 默认只读、显式隔离边界、失败只输出错误码，附准确运行步骤。
- 架构：`account_id = users.id`；旧 API 和 Cookie/Bearer 入口不改。新 password Identity 只是影子数据，不能用它取代当前 User 密码验证。

## 文件与数据库变化

| 文件 | 变化 |
| --- | --- |
| models.py | User.account_id 恒等属性；email_verified_at、auth_epoch(default 0)、updated_at |
| auth/mobile_models.py | Identity 类型/identifier/hash/验证及时间元数据；移动会话 epoch；迁移运行记录、原 ID 映射模型 |
| auth/identity_migration.py | 预检、旧 ID 严格解析、只新增的事务回填、重复检测、漂移拒绝、聚合报告 |
| migrations/versions/a6b7c8d9e0f1_unified_identity_compat.py | 独立加法迁移，接 f5a6b7c8d9e0；未使用字段可回退，已有新数据时拒绝破坏性 downgrade |
| scripts/ops/auth_migration.py | 不启动 Flask、不加载 .env 的隔离演练 CLI；校验 revision/备份文件摘要/写入确认 |
| tests/test_auth_identity_phase1.py | SQLite 迁移、冲突、原件/权限保持、故障回滚、旧凭据与恢复测试 |
| tests/test_auth_identity_postgres.py | PostgreSQL 并发回填、回滚、约束测试；每个测试独立随机 schema |
| .github/workflows/ci.yml | 现有 PG16 job 增加认证隔离演练 |

新增表只有 `auth_migration_runs`、`account_legacy_mappings`。不新增第二张 account 主表，不建邮件/找回/新网站会话表（后续阶段实现）。users 和 mobile_sessions 各新增字段见上；ExternalIdentity 新增 identity_type、identifier、password_hash、verified_at、updated_at、last_login_at。原值没有被 migration 更新。

### 对 Phase 0 候选方案的实现收敛

不扩大旧 subject 列，新增 255 字符 identifier 保存邮箱，web_password 的 subject 使用规范化邮箱 SHA256；已有 openid/旧 password-session 指纹完全保留。这样不必重建被会话外键引用的旧表。新增 web_password 的 identifier/user_id 各有部分唯一索引；PG 还检查其 owner、identifier、hash 非空和 client_id=web。SQLite 的老表升级不重建父表，非空组合条件由回填预检负责；ORM 新建的合成测试库有同名 CHECK，但不能用它替代真实 PG 迁移约束测试。

email/password_hash 仍非空；新增微信专用账号必须等空值兼容完善后另一个独立 Migration 才开启。auth_epoch 仅预留，不宣称已经实现全端注销。旧微信及 password-session Identity 类型保持 legacy，不批量重写 provider/subject。

## 迁移行为

1. 检查所有旧用户邮箱规范化碰撞、支持的历史 hash 格式、identity/session/challenge 归属、已有映射与影子数据漂移。
2. 停用且 hash=`!` 的匿名化账号仅建立 ID 映射，绝不变成登录身份。其他缺邮箱/异常 hash 保留原数据并报告人工处理，停止本次回填。
3. 活跃/正常停用账号逐个复制原 hash、created_at、last_login_at、状态。email_verified_at 默认 NULL，不能认定历史邮箱已验证。
4. 一次事务内插入 run、影子身份、恒等映射，随后对账。任一步失败调用方回滚整次事务；CLI 保证此行为。当前是**整库单事务隔离演练**，并非已实现超大生产分批迁移。真实人数核验后再决定分批游标/增量双写。
5. 重跑一致内容只记 skipped，不产生重复身份；旧密码/邮箱/启停已变化则报告漂移，不覆盖旧副本。Phase 2 统一凭据写入/双写完成前，影子数据不能成为认证权威。
6. 报告只含计数、run_id、错误类别，不含邮箱、密码、openid、原始 token 或数据库 URL。失败事务不会留下 run 行，失败聚合报告由操作员安全保存。

## 下一阶段门禁

先跑 PG16 CI 与实际生产同主版本隔离演练；真实用户统计、备份恢复与逐项对账仍缺失。完成后报告并等待进入 Phase 2 的确认；不直接开启小程序自动注册或执行生产迁移。
