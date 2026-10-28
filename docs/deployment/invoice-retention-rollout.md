# 发票留存功能发布与回滚

状态：网站候选代码独立审查、CI、真实备份恢复、PG16迁移演练和恢复库业务验收均已通过；准备0.9.47正式发布，尚未生产部署。仅涉及 Flask 主站，不需要重建 Gallery 或 Generation Service。
方案见 [实施计划](../product/invoice-retention-plan.md)、[API](../api/invoice-retention.md)、[ADR-0040](../adr/0040-invoice-retention-and-accounting.md)。

## 发布前 Go/No-Go

- [x] 业务候选 9199c0d 已经独立审查通过，本地 217 项与 PR CI 均通过；后续提交仍须 CI 验证。
- [x] PR #102 已将当前 main 同步到 develop，合并后两者文件树一致；功能经 develop / release PR 发布。
- [x] 已在独立恢复库及临时附件目录运行固定候选业务验收，不连接生产报销数据。
- [x] 操作者已在 PostgreSQL 16.14 恢复库反馈 MIGRATION_REHEARSAL_OK；63 张发票、79 个附件历史指纹及新增默认值检查通过。
- [x] 操作者反馈BUSINESS_OK、HISTORY_OK、STAGING_SMOKE_OK，实际API/Excel/原件/权限/撤销通过，既有发票和附件指纹保持一致。
- [ ] 记录本次备份位置、恢复结果、发布前 SHA 和负责人。
- [ ] 域名/DNS/TLS、systemd、数据库连接、服务器磁盘/内存、附件目录权限、数据库及附件备份、监控正常。
- [ ] Redis/COS 本次不变：确认现有平台状态正常；报销原件仍为本地 + DB BLOB，不声称已经迁移 COS。
- [ ] 防火墙不增加端口；环境变量无新增；浏览器本地压缩包不上传；新入口上传文件最大 20MB。
- [ ] 经业务人员完成下面的实际样例验收，并批准合并及生产发布。

缺少任一项不能上线；本地 SQLite 迁移及测试成功不能替代 PostgreSQL 演练。

## 已核实的服务器基线与演练备份

2026-10-28 操作者提供的只读检查：生产主站 SHA 为 f086b4f，systemd active，Python 3.12.3；PostgreSQL 与 pg_dump/pg_restore 同为 16.14，业务库约 22MB，迁移 d3e4f5a6b7c8。服务器尚有未提交的 Caddy 配置及本地备份，禁止 reset/clean 删除；后续发布要保留并核对这些改动。服务器运行环境以实际输出为准。

新增 `scripts/ops/invoice_backup.py` 供操作者在 Linux 服务器从部署目录手动执行（root）。可通过 `git fetch` + `git show <PINNED_SHA>:scripts/ops/invoice_backup.py` 提取到 `/root`，无需切换生产分支或更新应用工作树。执行前检查提取命令成功，不运行不完整文件。

脚本从运行中的 mytoolbox 环境及项目 config 的相同优先级确定数据库，只做只读版本/容量检查和 pg_dump，不导入 Flask、不迁移、不重启、不恢复、不删除文件。确认数据库与工具主版本相同、可用磁盘足够后，在 `/var/backups/mytoolbox` 创建随机唯一的 0700 目录，保存数据库 custom dump、发票附件、环境文件、Caddy 当前文件及其 Git diff、服务配置、Git SHA 和 SHA-256 manifest；文件均 0600。libpq 使用受限连接配置文件，连接凭据不进入命令参数、输出或子进程环境，说明见 [PostgreSQL 连接服务文件](https://www.postgresql.org/docs/16/libpq-pgservice.html)。

成功仅在所有步骤完成后生成 COMPLETE 并输出 BACKUP_OK 和备份位置。失败输出 BACKUP_FAILED，保留受保护的部分文件供本机排查，不把连接错误直接发到聊天。备份目录包含机密，禁止上传仓库、工单或聊天。

`pg_restore --list` 只是归档目录检查，**不代表恢复验证完成**，脚本始终标记 restore_verified=NO；下一步须恢复到独立库并演练迁移。该备份用于演练，数据库 dump 与在线附件目录并非同一文件系统原子快照；正式更新前仍须按维护窗口安排新的最终备份。

操作者已反馈演练备份 BACKUP_OK（dump 8,119,101 字节，源 SHA f086b4f）；随后恢复已成功（见下文）。创建恢复库时，PostgreSQL 16 的 `createdb` **没有** `--connection-limit` 参数；先用 `createdb --template=template0 --owner=postgres <全新测试库名>` 创建，再连接维护库执行 `REVOKE ALL ON DATABASE <测试库名> FROM PUBLIC; ALTER DATABASE <测试库名> CONNECTION LIMIT 3;`。不得把测试库名替换为生产库名，遇到同名库则停止而不是删除重建。依据：[createdb](https://www.postgresql.org/docs/16/app-createdb.html)、[ALTER DATABASE](https://www.postgresql.org/docs/16/sql-alterdatabase.html)。

恢复随后已由操作者验证成功：独立库仍为 d3e4f5a6b7c8，63 条发票、79 个附件，输出 RESTORE_OK。此后不得将生产服务连接切到该测试库。

本次迁移演练工件 `scripts/ops/invoice_retention_rehearsal.sql` 由真实 Alembic revision 离线生成 PostgreSQL DDL，专用于这一次发布，不是通用迁移服务。脚本在任何 DDL 前校验精确指定的恢复库名和旧迁移版本，在同一 psql 会话执行升级、降级、再升级；验证全部历史发票行、附件含 BLOB 内容的指纹未变，新增口径和打印默认值保留、审计表和索引存在，最后停留 e4f5a6b7c8d9 供候选版本验收。不导入 Flask、不读取生产配置、不重启、不修改生产库，不新增基础设施。

用 `git show <PINNED_SHA>:scripts/ops/invoice_retention_rehearsal.sql` 提取到受限文件后，只允许 `psql -X --set=ON_ERROR_STOP=1 --dbname=mytoolbox_invoice_verify_20261028_111850` 执行。成功输出 UPGRADE_OK、ROLLBACK_OK、REUPGRADE_OK、MIGRATION_REHEARSAL_OK。未见最终成功标记须停下诊断，不能改脚本中的数据库名保护或盲目重跑。该脚本**禁止在生产执行**；生产仅执行正常受控 Alembic upgrade，生产不 downgrade。本地契约测试确认工件与当前 revision 的实际 PostgreSQL DDL 完全一致，真实执行结果由操作者反馈后记录。

该 SQL 工件已独立只读复核通过，迁移契约测试 2 项通过；另在本机临时 PostgreSQL 18.6 集群上用合成发票/BLOB 执行三段迁移及错误库名拒绝测试，全部通过。操作者随后反馈 PostgreSQL 16.14 恢复库最终 MIGRATION_REHEARSAL_OK。本机结果与操作者反馈分别记录，不将本机版本说成生产版本。

2026-10-28 独立审查发现旧明细覆盖分摊、跨账单覆盖、历史附件别名误删、未分类税额遗漏和周期删除遗留原件五项问题，修复与回归已加入候选代码，必须复核后才能发布。更新后已打开的旧页面保存明细可能收到 409，需刷新后核对；不能绕过快照强制覆盖。

## 预发布验证（操作者服务器终端）

### 本次低资源恢复库业务验收

当前服务器使用 systemd，尚无常驻 Flask staging。为了不临时增加常驻服务，提供 `scripts/ops/invoice_staging_smoke.py`：将固定候选 SHA 用 `git archive` 展开到 postgres 专用 0700 新目录，禁止复制生产 `.env`；从主站虚拟环境借用解释器，但只导入候选模块，不导入 app/config、不启动 scheduler、不监听端口，不请求外部 OCR。

脚本只允许本次精确恢复库名 `mytoolbox_invoice_verify_20261028_111850`（本机 socket5432、角色 postgres），先验证 current_database 和迁移 e4f5a6b7c8d9，再创建随机测试账号及合成票据。全程不连接生产业务库、不迁移、不操作 systemd 或 Caddy。原有发票、含 BLOB 附件逐行摘要前后必须一致。它会向恢复库增加测试账号和业务数据，不会清库；失败后停下检查，不重跑迁移演练 SQL。

验收覆盖加油票零费用、两个月60公里保留、6月590.48元手工分摊、7月不变、总费用650.48元、过期快照409、Excel单元格合计、只打印选中原件、删本轮临时磁盘缓存后BLOB取回、另一账号隔离、审计及撤销。成功输出 `BUSINESS_OK`、`HISTORY_OK`、`STAGING_SMOKE_OK`。失败输出固定阶段标识，不输出数据库连接或原始异常；不得将失败算作验收通过。

该无监听业务验收补足恢复库的真实候选 API/Excel 验证；浏览器样式、ZIP 下载和实体打印仍按下方人工清单完成。它不是 Vercel/独立常驻 staging 已搭建的证明。此次不改变 Gallery/Generation 运行工件，部署方式沿用现有主站 systemd，容器晋级要求不适用于这一未容器化服务。

操作者命令由发布协作提供固定 SHA，采用以下形式（`<PINNED_SHA>` 需替换为已审查且 CI 通过的实际提交，不能执行占位符）：

```bash
cd /opt/mytoolbox || exit 1
set -euo pipefail
git fetch origin codex/invoice-retention-workflow
candidate=<PINNED_SHA>
stage_dir="/var/lib/postgresql/mytoolbox-invoice-stage-${candidate}"
test ! -e "$stage_dir"
install -d -m 0700 -o postgres -g postgres "$stage_dir"
git archive "$candidate" | sudo -u postgres tar -x -C "$stage_dir"
test ! -e "$stage_dir/.env"
git show "$candidate:scripts/ops/invoice_staging_smoke.py" > /root/mytoolbox-invoice-staging-smoke.py
chmod 0600 /root/mytoolbox-invoice-staging-smoke.py
sudo -u postgres /opt/mytoolbox/.venv/bin/python - "$stage_dir" < /root/mytoolbox-invoice-staging-smoke.py
```

目的：不切换生产工作树、不覆盖未提交配置，就能执行固定代码的恢复库验收。目录已存在、模块缺失、数据库版本不符或验收失败均停止；不要删除已有目录或修改数据库保护来继续。权限/解释器失败时先核对 postgres 对 `/opt/mytoolbox/.venv` 的读/执行权限；不改生产目录为777，不把生产环境文件复制到验收目录。

### 已有独立 staging 的通用方式

请在已经按平台部署手册创建的 staging 实例操作。不要把生产 `.env` 原样复制到 staging。

```bash
git status --short
git fetch origin
git switch --detach <REVIEWED_COMMIT_SHA>
.venv/bin/pip install --requirement requirements.txt
export FLASK_APP='app:create_app'
export AUTO_CREATE_SCHEMA=false
.venv/bin/flask db current
.venv/bin/flask db heads
.venv/bin/flask db upgrade
.venv/bin/flask db current
```

工作区应为空，heads/current 最终为 e4f5a6b7c8d9。数据库必须确认是 staging；迁移失败停止发布，不跳过报错或 stamp 伪装成功。重启 staging 自己的服务（不要误重启生产服务）。

## 人工验收

1. 历史周期的金额、打印和 Excel 与发布前样本一致；派车费用在首页卡片、周期卡片、汇总、封面与费用分类表一致。
2. 上传加油票，用途选加油票，无需金额，保存后在列表可见；公里数和本期费用不变。
3. 提取 ZIP（含嵌套包、trans/apply、重复 PDF），逐张确认示例金额 0.9/1/1.3/4.99/5/20.4。按默认 5 元筛选，5 元保留，未知票据标记待确认且电子件仍在。
4. 点保存全部票据，选择报销周期、用途和发生月。未勾选票据也保存；确认网站列表和打印清单选择一致。中断后在原页面重试，不重复生成记录。
5. 下载完整归档包，解压检查原 ZIP、全部提取 PDF、清单 JSON 均完整。只有下载成功后才关闭提取页面。原 ZIP 此次不进入服务器数据库。
6. 上传通行账单，独立填写发生月、结算月，核对金额后勾选确认，保存。示例 590.48 只是测试数据。
7. 先保存对应月派车行，进入分摊弹窗，仅选择同自然月行，预览、改成非平均值、确认，行和必须精确 590.48；其他月份保持原值。Excel 过桥费列与网站相同。
8. 重新点击旧确认请求、选择其他用户/周期或错月份行应失败；不能重复分摊到另一组行。撤销恢复原值；分摊后修改过派车单则撤销提示冲突。
9. 两账号隔离，不能访问别人的票据原件、账单、审计或周期。测试伪造文件扩展名、超过 20MB、金额 NaN/负数/三位小数以及月份错误。
10. 通行账单与发票差额只显示核对；不把原始票面金额再次汇总。提取页目前人工确认金额，不宣称已经提供离线 OCR。

## 生产更新（全部门禁通过并获发布批准后）

本次版本0.9.47，用户已明确批准生产部署，发布负责人负责PR/版本和审核证据，操作者执行服务器命令并兼任数据库/回滚操作负责人。CI/复核和main发布提交确定后才发实际固定SHA命令。无需重建其他服务，也不安装新依赖；最终脚本会验证requirements.txt与旧版完全一致。

一次性 `scripts/ops/invoice_release.py` 和已审核 `invoice_backup.py` 必须从**同一批准SHA**提取至root专用目录。发布工具在preflight前持有固定root文件的非阻塞互斥锁，并发第二次执行只报告busy，不操作服务。仅支持本次已知旧生产SHA f086b4f、main、已拉取origin/main精确目标；目标必须包含已验收7f751fe且其后只有发布脚本/测试/文档更改。任何未验收业务变化、额外迁移、依赖或仓库Caddy变动都会拒绝。工作树只允许已知Caddy未提交修改，不接受任何暂存修改；不删除既有未跟踪备份，不reset/stash。

脚本先按运行中service环境/项目config一致的优先级确定数据库，再stop主站。保持停写完成最终DB及原件/配置备份，根目录0700、文件0600；manifest注明停写最终备份和目标SHA。验证备份旧迁移d3，快进main到批准SHA，核对.env及本地Caddy哈希未变。用最小Flask-Migrate应用执行正常Alembic upgrade到e4（不导入app、不启动调度器、不create_all），检查历史发票/含BLOB附件内容指纹及默认口径均保留，然后start主站及校验active/HTTPS healthz。migration连接有15秒锁等待和120秒语句超时，不无限挂起。

这是现有systemd的本次受控运维工件，不是新的发布平台。停站时域名可能短暂不可用，请执行整段命令，不在中间停留等待聊天。数据库dump与原件均在主站停写期间完成；同一数据库其他服务仍可能写自己的表，pg_dump本身提供事务一致快照，未经此次修改的服务保持原运行方式。

```bash
(
set -euo pipefail
cd /opt/mytoolbox
git fetch origin main
release=<APPROVED_MAIN_SHA>
test "$(git rev-parse origin/main)" = "$release"
install -d -m 0700 /root/mytoolbox-invoice-release
for script in invoice_backup.py invoice_release.py; do
  git show "${release}:scripts/ops/${script}" > "/root/mytoolbox-invoice-release/${script}"
  chmod 0600 "/root/mytoolbox-invoice-release/${script}"
done
.venv/bin/python /root/mytoolbox-invoice-release/invoice_release.py "$release"
)
```

预期输出DEPLOY_OK、release_commit、migration_revision=e4f5a6b7c8d9、backup_dir、service=active; HTTPS_health=OK。报告这些固定结果即可；随后按人工验收第1/2/6/7项做实际检查。healthz只是HTTP存活，不能代替脚本的数据库/内容核验或用户实际业务验收。

失败输出DEPLOY_FAILED阶段及root专用日志位置，只贴固定失败行，不上传日志/备份/连接配置。主站尚未切换代码且最终备份失败时自动尝试恢复旧服务；一旦切换代码或进入迁移则保持停写，不盲目运行旧版。不要重跑脚本绕过旧SHA保护，先按失败阶段诊断。未出现DEPLOY_OK不算上线成功。生产备份新工件标记restore_verified仍为false，指该次新dump未再次恢复；历史真实恢复及迁移验收已验证备份链路，不伪称本次最终dump也已恢复。

工件本地验证：8项故障/互斥/恢复保护测试通过；在临时PostgreSQL18合成数据库实际调用同一个最小Flask-Migrate函数完成d3→e4，历史发票/BLOB及默认口径一致，服务已停止。正式服务器此前PG16恢复库已完成原始DDL演练和API/Excel业务验收；本机PG18结果不替代服务器版本证据。正式主站执行结果仍待操作者反馈。

## 失败恢复与回滚

- Git 工作区不干净、HEAD 不符合计划：停止，不使用 reset --hard 清理未知改动。
- 迁移失败：保持停写，检查数据库连接和 migration current；在隔离恢复库复现，不执行 stamp 跳过迁移。
- 服务启动失败：本机查看 `journalctl -u mytoolbox -n 100 --no-pager`，对外只提供脱敏错误；不要复制完整带业务数据的日志。
- 尚未有新口径数据时，可在保留新增列的情况下 `git switch --detach <PREVIOUS_SHA>` 后重启。
- **已有留存/待确认票据后，禁止直接运行旧版本并恢复费用导出**。旧程序会忽略 inclusion_policy，导致留存票据被重复计入。应维持维护窗口，优先前滚修复，或先准备兼容口径的回滚版本并验证。
- 数据恢复须在隔离库用 `pg_restore` 演练、核对后由数据库负责人执行；正式恢复会丢失备份之后写入，必须提前确认停写窗口与数据影响。不在生产直接执行本迁移 downgrade。

## 小程序发布边界

本次网站更新不包含已可发布的微信小程序。需要主体/AppID、官方文档核验、绑定与令牌鉴权实现、开发者工具/真机验证、合法域名及隐私审核。后续开发提示词见[手机录入实施提示词](../product/wechat-invoice-upload-codex-prompt.md)。
