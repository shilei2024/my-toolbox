# 06 Phase 1 隔离演练指南（不是生产部署指令）

本文保留 Phase 1/2 的分步演练。当前完整候选请使用[统一账号人工更新与验收](10-release-runbook.md)，其中完整恢复库工具运行与生产相同的三阶段事务迁移；不要将本页 upgrade-auth 当作最终升级。

新功能未上线。此 CLI 只允许已有 `auth_rehearsal_*.db` SQLite 文件，或 PG 的 `auth_rehearsal_*` schema，拒绝 public schema；禁止拿生产库改名来通过检查。不要粘贴连接密码、邮箱或原始数据到聊天。

## 1. 自动合成演练（无真实用户）

在项目根目录：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_auth_identity_phase1 -v
```

预期 12 项通过。测试建立临时 SQLite，覆盖 schema 升级、重复回填、故障回滚、旧 Cookie/两种移动 Token、BLOB、授权及备份恢复，结束后清理临时目录。失败应先修复，不能继续真实数据演练。

## 2. PostgreSQL 合成演练

准备专用测试 PG 数据库，操作员在本机安全设置 `AUTH_TEST_DATABASE_URL`，值不要放命令历史、Git 或报告。测试角色需能在此测试库创建/删除 schema，不能指向生产。运行：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_auth_identity_postgres -v
```

预期 3 项通过且没有 skipped。缺少环境变量会显示 skipped，此结果不算 PG 验收。测试创建随机 `auth_rehearsal_*` schema，清理只针对本次 schema。已接入 CI 的 PG16 job；本地本次未运行成功，因为无 PG 运行环境。

## 3. 已有隔离库 CLI 预检

仅当操作员已准备具备旧完整 schema 与 Alembic revision 的隔离演练库时使用。连接从唯一环境变量 `AUTH_MIGRATION_DATABASE_URL` 读取，不读取项目 .env，不接受 URL 命令参数。

SQLite：文件名必须符合 `auth_rehearsal_名称.db`，且必须存在。PG：必须显式指定已存在的 `auth_rehearsal_*` schema；search_path 不包含 public。实际生产恢复库结构若不符合这一路径，**先停止并另行评审恢复库适配**，不要手工改生产 schema。

```powershell
.venv\Scripts\python.exe scripts/ops/auth_migration.py check
```

PG 示例（schema 名替换为专用演练 schema）：

```powershell
.venv\Scripts\python.exe scripts/ops/auth_migration.py check --schema auth_rehearsal_review
```

预期 `ready: true`，`scanned` 为合成/恢复用户数，`errors: {}`。`phase1_schema_present: false` 表示仍在旧 revision，不是丢数据。旧 revision 仅接受 f5a6b7c8d9e0，未知/多 head 拒绝操作。

## 4. 写入前备份与确认

停掉隔离库所有应用写者。SQLite 用安全快照/停止连接后的完整复制，PG 用 pg_dump 保存该隔离 schema 并在另一个隔离位置恢复验证。文件摘要相同只证明备份文件未变，不能代替恢复验证。

在备份目录手工准备下列 manifest（占位摘要必须替换为真实 SHA256）：

```json
{
  "kind": "auth-rehearsal-backup-v1",
  "files": {"backup.dump": "文件的64位小写SHA256摘要"}
}
```

备份文件必须与 manifest 同目录；路径跳转、缺文件和摘要错误会被拒绝。manifest 不含连接或用户内容。PG 的实际导出/恢复环境未提供，本轮不编造可直接执行的生产备份命令。

## 5. 结构升级、回填与再次核验

以下是 SQLite 演练示例；PG 每条均追加 `--schema auth_rehearsal_review`。

```powershell
.venv\Scripts\python.exe scripts/ops/auth_migration.py upgrade --ack-isolated-database --writers-stopped --backup-manifest BACKUP_MANIFEST.json
.venv\Scripts\python.exe scripts/ops/auth_migration.py check
.venv\Scripts\python.exe scripts/ops/auth_migration.py apply --ack-isolated-database --writers-stopped --backup-manifest BACKUP_MANIFEST.json
.venv\Scripts\python.exe scripts/ops/auth_migration.py check
```

结构升级先进行旧数据预检，只接收预期 parent，成功更新 revision；重复执行返回 already_applied。回填预期 `inserted + skipped = scanned`；停用 `!` 账号计入 skipped/excluded_disabled；完成后 preflight 的 identities_to_create 与 mappings_to_create 均为 0。重复 apply 应 inserted=0，映射数不变。

## 6. 常见失败

- `ready:false`/errors 非空：根据聚合类别在隔离环境人工核验，不默认改用户数据；禁止复制真实异常明细到公开文档。
- `auth_rehearsal_failed`：检查环境变量、隔离 schema/文件名、连接权限、revision、备份摘要及写入确认参数；工具故意不打印可能含凭据的驱动异常。
- 锁超时：检查是否确实停止写者，PG 回填锁定 users/identity/mapping，5 秒未取锁会失败回滚。
- `shadow_identity_drift` / `mapping_drift`：回填后旧应用曾改密码/邮箱/状态。不要强制覆盖；Phase 2 双写方案落地前，旧 User 仍为权威。

生产部署另需域名/TLS、Cookie/代理、共享限流、原件/AI数据库完整备份、容量、监控及回退最低版本核验。Phase 1 单独完成不足以发布统一注册系统。


## 7. Phase 2 隔离升级（不是生产命令）

先完成前述 Phase 1 upgrade/apply/check，停写并重新生成/校验备份 manifest。仍使用同一专用 AUTH_MIGRATION_DATABASE_URL；PG 必须指定隔离 schema。工具不加载 Flask 或 .env，不接受 public schema。

```powershell
.venv\Scripts\python.exe scripts/ops/auth_migration.py upgrade-auth --ack-isolated-database --writers-stopped --backup-manifest BACKUP_MANIFEST.json
.venv\Scripts\python.exe scripts/ops/auth_migration.py check
```

PG 每条追加 `--schema auth_rehearsal_review`。预期 revision=b7c8d9e0f1a2、status=applied；重复执行应为 already_applied。未回填、旧版本不符或备份不符应拒绝。新结构只新增 WebSession/审计表，不迁移发票、用户ID或原件。禁止运行 Phase 2 应用连接只有 Phase 1 结构的数据库。

Phase 2 应用 `AUTH_LEGACY_COOKIE_UNTIL` 默认空：旧网站 Cookie/Remember 需要重新登录一次，原账号和密码继续有效。如果必须短期保留旧登录，发布时设置一个明确且短期的 UTC 截止值，例如 ISO-8601 的 `YYYY-MM-DDTHH:MM:SSZ`（替换为真实截止时间），到期不再接受。无时区/无效值均拒绝兼容。重置密码或撤销后即使尚未到截止时间也不接受旧凭据。不要随意延长兼容窗口。

成功验证：网站注册/登录→关闭会话后 Remember 恢复→Gallery 身份；微信与密码两种移动登录→发票列表；网站重置后所有旧端退出；新密码可登录；禁用再启用不恢复旧凭据；退出确认页需 POST/CSRF。不得通过改 epoch 或删除审计来解决登录失败。

常见故障：缺少新表表示迁移未完成，应停应用并在隔离库重现迁移；旧 Cookie 失效属于预期，重新登录；check 在合法密码/状态变更后报 source_digest 漂移表示原始回填基线已变化，需要结合安全审计核对，不能反向覆盖新密码。原回填映射是迁移证据，不是持续同步任务。

发布门禁继续包括 PG16 两项认证并发、三项迁移并发/约束、真实恢复库对账、完整预发布、备份恢复与审查。域名/TLS/进程/数据库/Redis（若使用）/COS/环境变量/防火墙/容量/监控沿用生产发布清单；本轮没有验证这些生产条件。新会话和审计均保存在 PostgreSQL，无新增基础设施；应监控表大小，清理过期会话前先确定审计保留周期，当前不自动删除安全记录。
