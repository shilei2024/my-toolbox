# 统一账号系统：人工更新与验收

适用域名：`https://mindfulpenpal.com`。目标数据库版本：`c8d9e0f1a2b3`。

这份指南是发布候选的操作手册，不代表生产已升级。服务器和微信后台由操作员执行。所有命令在 Ubuntu 的 Bash 中运行，逐段执行；看到失败立即停止，不接着执行下一段。不要把 `.env`、数据库连接、邮件链接或完整日志发到聊天。

## 1. 发布前条件

- 固定候选提交通过代码审查、Python/Node/Gallery CI，以及 PG16 迁移与并发测试。
- 下述隔离恢复迁移通过；恢复库里的旧用户、票据、原件、客户和授权完成对账。
- 同一候选完成预发布：老账号登录、普通账号新增客户、网站/小程序客户与等级一致、Excel、原件下载、新微信注册、绑定冲突、改密及全端退出。
- DNS/TLS 正常；systemd/Docker 正常；数据库、Redis、COS 的既有连接和权限正常；防火墙不开放内部服务；磁盘可容纳完整备份和恢复库；监控和备份留存正常。参照[生产发布清单](../operations/release-checklist.md)。
- 多进程生产必须设置 `RATELIMIT_STORAGE_URI` 到既有共享 Redis 的专用限流库，并核对代理来源/IP配置。默认 memory:// 只适合本地，不能作为生产账号防爆破验收。连接保存在 .env，不能公开；Redis不可用时先恢复限流存储，不临时关闭限流放行。
- 真实邮件已投递并完成验证/找回；微信体验版已通过。配置检查或 mock 测试不能替代这两项。
- 合并、维护窗口及部署已获授权。先合并到 main，再部署固定 SHA；不要部署浮动分支。

这些条件未完成时，只执行准备和隔离演练，不执行第 4 节。

## 2. 获取候选，保护现有配置

在生产服务器以 root 执行（这一步只同步 Git 引用）：

```bash
cd /opt/mytoolbox
git fetch origin
SOURCE=$(git rev-parse HEAD)
TARGET=$(git rev-parse origin/main)
printf 'source=%s\ntarget=%s\n' "$SOURCE" "$TARGET"
git branch --show-current
git diff --name-only HEAD
git diff --cached --name-only
systemctl is-active mytoolbox
```

预期分支 main、服务 active，已跟踪改动只有既有 `services/generation-service/deploy/Caddyfile.production`，暂存区为空。**TARGET 必须是本次审查和演练过的合并提交**，不是看到 main 有更新就继续。生产曾报告 `f5a6b7c8d9e0`、PG16.14；发布脚本会重新核对数据库，旧信息不能替代本次检查。

将发布工具复制到工作区外，避免升级途中脚本被替换：

```bash
install -d -m 700 /root/mytoolbox-auth-release
for name in auth_release.py invoice_backup.py invoice_release.py; do
  git show "$TARGET:scripts/ops/$name" > "/root/mytoolbox-auth-release/$name" || break
  chmod 700 "/root/mytoolbox-auth-release/$name"
done
test -s /root/mytoolbox-auth-release/auth_release.py
```

三个文件都应成功导出。若提示路径不存在，说明目标尚未包含本次改动，停止。

## 3. 完整恢复库演练

使用独立测试数据库 `auth_rehearsal_release`，不能把生产库改名。操作员先用现有备份工具生成备份：

```bash
cd /opt/mytoolbox
/opt/mytoolbox/.venv/bin/python /root/mytoolbox-auth-release/invoice_backup.py
```

预期 `BACKUP_OK`，记录输出的 `backup_dir`。这只是备份成功，还不是恢复成功。停掉或隔离其他写者后生成的备份才能作为跨数据库/文件一致性验收依据。

在隔离测试主机上，用 PG16 客户端恢复上述 `database.dump`；路径由操作员输入，不粘贴占位符执行：

```bash
read -r -p '输入已复制的 database.dump 绝对路径: ' DUMP
test -f "$DUMP"
sudo -u postgres createdb auth_rehearsal_release
sudo -u postgres pg_restore --exit-on-error --no-owner --no-privileges -d auth_rehearsal_release < "$DUMP"
```

数据库已存在时停止，另建新的隔离库；不执行自动删除。恢复发生任何错误都不能继续。测试账号必须仅有该恢复库权限。外部 COS 原件应只读检查，测试应用禁用真实收费任务、通知和后台写者。

在隔离主机的**候选代码目录**准备本地备份清单；该清单只验证文件未变化：

```bash
python3 -c 'import hashlib,json,sys,pathlib; p=pathlib.Path(sys.argv[1]).resolve(); h=hashlib.file_digest(p.open("rb"),"sha256").hexdigest(); (p.parent/"auth-rehearsal-manifest.json").write_text(json.dumps({"kind":"auth-rehearsal-backup-v1","files":{p.name:h}}))' "$DUMP"
read -r -s -p '输入仅指向隔离恢复库的 SQLAlchemy PostgreSQL URL: ' AUTH_MIGRATION_DATABASE_URL
printf '\n'
export AUTH_MIGRATION_DATABASE_URL
.venv/bin/python scripts/ops/auth_release_rehearsal.py --ack-isolated-database --writers-stopped --backup-manifest "$(dirname "$DUMP")/auth-rehearsal-manifest.json"
unset AUTH_MIGRATION_DATABASE_URL
```

预期 `AUTH_REHEARSAL_OK revision=c8d9e0f1a2b3`。它运行与生产相同的三阶段事务迁移和历史摘要核对，不启动 Flask、不自动建用户。只接收名字以 `auth_rehearsal_` 开头的专用 PG 数据库。

随后让预发布应用连接该恢复库，执行第 1 节所有业务验收；记录用户/业务/原件对账结果和候选 SHA。新微信注册仅获得发票助手权限。测试邮箱使用操作员自己的地址；不要向历史用户群发验证邮件。演练失败时保留隔离库供排查，从未升级的备份创建另一个隔离库重试。

## 4. 生产网站升级

维护窗口内先停止**实际运行的**其他写者（邮件定时器、任务调度、Generation workers 等）。用 `docker compose ls` 和既有部署清单确认真实项目；本仓库有两套历史 compose 文件，不能猜一个执行。保留反向代理以便健康检查。发布脚本会停止并启动 `mytoolbox`，不会管理其他项目。

`/opt/mytoolbox/.env` 初始保持：

```dotenv
APP_BASE_URL=https://mindfulpenpal.com
AUTH_LEGACY_COOKIE_UNTIL=
AUTH_MAIL_ADAPTER=disabled
WECHAT_MINI_REGISTRATION_ENABLED=false
```

通过 `sudoedit /opt/mytoolbox/.env` 修改；保留 SECRET_KEY、数据库、SMTP 和所有既有参数。旧网站 Cookie 需要重新登录一次；账号、密码和发票保留。

**仅当恢复、预发布验收实际完成**，在第 2 节同一个 shell 中执行：

```bash
cd /opt/mytoolbox
/opt/mytoolbox/.venv/bin/python /root/mytoolbox-auth-release/auth_release.py --source "$SOURCE" --target "$TARGET" --restore-verified --staging-verified
```

预期 `AUTH_RELEASE_OK`、固定 release_commit、`revision=c8d9e0f1a2b3` 和新的 backup_dir。工具会停写、生成最终备份、保留 .env/Caddy、快进 main、事务迁移和回填、核对历史摘要、重启并检查正式域名。它拒绝依赖/Caddy版本变化、非预期数据库版本和未提交的其他改动；遇到拒绝不要删除检查。

```bash
systemctl is-active mytoolbox
curl --fail --silent --show-error https://mindfulpenpal.com/healthz
```

预期 active 和 status=ok；然后用已有普通账号验证发票、客户、原件与导出。健康检查只证明服务可访问，不代表业务验收完成。

## 5. Gallery 与下游会话撤销

Gallery 前端部署在 Vercel，使用同一候选代码更新 `apps/gallery-web`，检查构建成功、域名和既有内部签名配置。不要在腾讯服务器另起一个 Gallery 前端。

Generation API 使用同一候选构建并按**已在用的**生产 compose 项目更新，沿用其镜像摘要发布流程。完成 Flask + Gallery BFF 更新后，在该服务实际 env 文件设置 `AUTH_ENFORCE_SESSION=true` 并重建 API 容器。数据库角色需对 `public.users` 与 `public.account_web_sessions` 有 SELECT 权限；不要因此授予超级用户。

最终验收：登录后 Gallery 正常；退出、改密或禁用后原网站及 Gallery 请求均被拒绝，重新登录恢复。这个开关未开启时只算兼容过渡，不算全端撤销已验收。若部署项目名/镜像配置不同，按[现有部署指南](../deployment/README.md)使用真实参数，不能直接复制另一套 compose 启动第二套服务。

## 6. 启用既有 SMTP

复用现有 SMTP，不替换密码。通过 sudoedit 将 `AUTH_MAIL_ADAPTER=smtp`；确认原 SMTP_HOST、SMTP_FROM、SMTP_PORT、SMTP_SECURITY（ssl/starttls）、SMTP_USERNAME/PASSWORD 配对配置仍在。不要输出这些值。

```bash
cd /opt/mytoolbox
systemctl restart mytoolbox
install -m 644 deploy/auth-mail.service /etc/systemd/system/auth-mail.service
install -m 644 deploy/auth-mail.timer /etc/systemd/system/auth-mail.timer
systemctl daemon-reload
systemctl start auth-mail.service
systemctl show auth-mail.service -p Result -p ExecMainStatus
systemctl enable --now auth-mail.timer
systemctl is-active auth-mail.timer
```

预期 Result=success、ExecMainStatus=0、timer active。服务先检查配置再派发，失败重试最多 3 次。首次无任务正常；**检查成功不证明邮件已投递**。

以操作员账号访问 `/account/security`，点击验证邮箱、收信并确认，再从 `/account/recover` 测试找回。只打开链接不消费令牌，提交确认后才生效。旧链接再次提交应失败，改密后网站、小程序和 Gallery 的旧会话均退出。真实邮件未通过时关闭邮件功能并修复 SMTP，不开放不可靠的找回入口。

## 7. 小程序上线

1. 开发者工具导入 `apps/invoice-miniprogram`；使用既有 AppID 和正式 API 域名，不改成示例配置。
2. 上传体验版；在隔离预发布先验证注册、客户/等级、上传重试、绑定确认、网站登录设置、票据与 Excel 同步；既有用户须仍能看到历史数据。
3. 审核说明与隐私声明包含账号、票据及邮箱用途；更新图标，完成微信平台审核。
4. 配套小程序版本就绪后，将网站 `.env` 中 `WECHAT_MINI_REGISTRATION_ENABLED=true`，执行 `systemctl restart mytoolbox`，发布小程序并以新微信验收。

验收：首次微信登录即可进入发票助手，普通账号可新增个人客户，无管理员/CRM/FCST权限；网站与小程序使用相同账号；已有两份账号冲突时拒绝自动合并。开启注册后旧客户端的直接绑定流程会提示更新；需同步发布新版并告知使用者更新。

## 8. 故障与恢复

- `AUTH_RELEASE_FAILED stage=...`：脚本保持主站停止，防止旧代码读写新身份结构。只在服务器私下查看输出目录里的 release.log；不要粘贴完整日志。
- migration 阶段失败：迁移事务整体回滚，但代码可能已快进。先核对 revision 和备份，修复原因，不能盲目重新运行需要旧 revision 的发布器。
- 迁移成功、启动失败：保留新 schema，修复配置/代码前进；不要 `alembic downgrade`、清会话表或 git reset 到旧认证实现。
- 邮件故障：`systemctl disable --now auth-mail.timer`，将 AUTH_MAIL_ADAPTER 改 disabled，重启主站；网站原密码登录仍可使用。
- 注册故障：将 WECHAT_MINI_REGISTRATION_ENABLED 改 false 并重启；保留已注册用户，不能回退到假定 email/password 非空的旧代码。
- 确需整体灾难恢复：进入维护窗口，停止全部写者，用已演练的备份恢复到**新数据库**，核对业务/原件，再切换匹配代码和连接。恢复会丢失备份后写入，必须先记录并安排对账；禁止直接覆盖唯一生产库。

保留最终备份、候选 SHA、验收记录。上线后监控登录失败、邮件 failed/pending 数量、定时器状态、数据库容量和错误率；当前不自动删除身份审计记录。
