# 发票留存功能发布与回滚

状态：候选代码独立审查及 CI 通过，备份已真实恢复；恢复库迁移与预发布验收进行中，尚未生产部署。仅涉及 Flask 主站，不需要重建 Gallery 或 Generation Service。
方案见 [实施计划](../product/invoice-retention-plan.md)、[API](../api/invoice-retention.md)、[ADR-0040](../adr/0040-invoice-retention-and-accounting.md)。

## 发布前 Go/No-Go

- [x] 业务候选 9199c0d 已经独立审查通过，本地 217 项与 PR CI 均通过；后续提交仍须 CI 验证。
- [ ] 当前 develop 落后 main，须先同步生产基线并走集成/发布分支流程，禁止把旧 develop 直接发布。
- [ ] 预发布使用独立数据库与附件目录，不能让 Preview 读写生产报销数据。
- [ ] 生产备份恢复到隔离 PostgreSQL，演练 d3e4f5a6b7c8 → e4f5a6b7c8d9，检查旧记录 expense/invoice/打印选中/金额确认均保留。
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

该 SQL 工件已独立只读复核通过，迁移契约测试 2 项通过；另在本机临时 PostgreSQL 18.6 集群上用合成发票/BLOB 执行三段迁移及错误库名拒绝测试，全部通过，临时服务已停止。这不能替代服务器 PostgreSQL 16.14 上的真实备份恢复库验证，后者仍等待操作者执行。

2026-10-28 独立审查发现旧明细覆盖分摊、跨账单覆盖、历史附件别名误删、未分类税额遗漏和周期删除遗留原件五项问题，修复与回归已加入候选代码，必须复核后才能发布。更新后已打开的旧页面保存明细可能收到 409，需刷新后核对；不能绕过快照强制覆盖。

## 预发布验证（操作者服务器终端）

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

以下以仓库已有 systemd 主站部署为准。先在服务器记下旧 SHA，不要把密钥、数据库口令或真实发票发到聊天中。

```bash
cd /opt/mytoolbox
git status --short
git rev-parse HEAD
mkdir -p backups
set -a
. ./.env
set +a
pg_dump --format=custom --file="backups/before-invoice-retention-$(date +%Y%m%d-%H%M%S).dump" "$DATABASE_URL"
tar -czf "backups/invoice-files-$(date +%Y%m%d-%H%M%S).tar.gz" uploads/reimbursement
```

目的：数据库和附件一起保留，避免只回滚代码却丢失票据。备份失败/磁盘空间不足必须停止。先确认可恢复备份，再进入短维护窗口（停用报销录入和导出；若没有单模块维护开关，应暂停主站服务并说明用户影响）。

```bash
sudo systemctl stop mytoolbox
git fetch origin
git switch main
git pull --ff-only origin main
.venv/bin/pip install --requirement requirements.txt
export FLASK_APP='app:create_app'
export AUTO_CREATE_SCHEMA=false
.venv/bin/flask db current
.venv/bin/flask db upgrade
.venv/bin/flask db current
sudo systemctl start mytoolbox
sudo systemctl status mytoolbox --no-pager
curl --fail --silent --show-error https://mindfulpenpal.com/healthz
```

预期：迁移头为 e4f5a6b7c8d9，服务 active (running)，healthz 成功；随后按人工验收第 1/2/6/7 项做实际检查。确认 main 是已批准且 CI 全绿的发布提交，不能直接把功能分支部署生产。

## 失败恢复与回滚

- Git 工作区不干净、HEAD 不符合计划：停止，不使用 reset --hard 清理未知改动。
- 迁移失败：保持停写，检查数据库连接和 migration current；在隔离恢复库复现，不执行 stamp 跳过迁移。
- 服务启动失败：本机查看 `journalctl -u mytoolbox -n 100 --no-pager`，对外只提供脱敏错误；不要复制完整带业务数据的日志。
- 尚未有新口径数据时，可在保留新增列的情况下 `git switch --detach <PREVIOUS_SHA>` 后重启。
- **已有留存/待确认票据后，禁止直接运行旧版本并恢复费用导出**。旧程序会忽略 inclusion_policy，导致留存票据被重复计入。应维持维护窗口，优先前滚修复，或先准备兼容口径的回滚版本并验证。
- 数据恢复须在隔离库用 `pg_restore` 演练、核对后由数据库负责人执行；正式恢复会丢失备份之后写入，必须提前确认停写窗口与数据影响。不在生产直接执行本迁移 downgrade。

## 小程序发布边界

本次网站更新不包含已可发布的微信小程序。需要主体/AppID、官方文档核验、绑定与令牌鉴权实现、开发者工具/真机验证、合法域名及隐私审核。后续开发提示词见[手机录入实施提示词](../product/wechat-invoice-upload-codex-prompt.md)。
