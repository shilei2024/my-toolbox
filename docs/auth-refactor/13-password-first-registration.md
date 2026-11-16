# 注册页设置密码，邮件确认完成注册

2026-11-17，用户明确要求改为：邮箱+密码+确认密码 → 验证邮件 → 点击确认 → 正式注册 → 注册成功邮件。

## 设计与门禁

- 生产影响：d9新增一列待验证密码摘要，旧用户/数据保持；新申请在注册页完成密码校验，正式User仍只在验证后创建。先迁移再更新代码。
- 复用：继续使用平台待验证申请、一次性token、邮件任务、统一密码哈希与账号身份；不新增服务或供应商。
- 简化/成本：待验证记录保存Werkzeug单向密码摘要，不存明文；复用已有投递进程及发布器。列可空以兼容已经发出的d9旧注册链接。
- 维护：公开注册恢复三项常见输入，确认页不再重复设密；过期重发保留已提交密码。旧d9链接允许按原流程完成，避免已发邮件失效。
- 架构：正式账号创建/验证标记/欢迎任务仍原子完成，无额外授权和会话。微信注册即用不变。

## 安全与兼容

初始提交仅保存哈希，不会登录；新链接只展示确认按钮，GET不激活以避免邮件扫描器误消费，POST需CSRF和同源来源。重复注册更换密码必须同时失效旧token并取消旧待发任务，邮件链接绑定同一份密码摘要；单纯重发不得改密码。既有账号不可覆盖，激活请求不得另行更换已提交密码。

完成注册后清除申请中的临时密码摘要，由正式账号及既有密码身份保存凭据，减少不必要的长期副本。

常规预设密码注册存在“他人为你的邮箱发起注册”的固有风险：邮件明确提示非本人操作请忽略；本次按用户明确流程决策，不再要求邮箱页面重新设置密码。配套测试防止旧链接被用于激活后来更改的密码。

## 范围与验证

涉及forms/routes/registration_service/models、注册/确认/等待邮件文案、e0迁移、既有发布与验收工具、测试和文档。e0f1a2b3c4d5基于d9e0f1a2b3c4，只新增account_registrations.password_hash nullable。

验证三字段校验、确认页无密码、原密码登录、未验证无User/session、重发/更改密码失效旧链接、旧d9邮件兼容、欢迎一次入队、密码重置闭环，以及PG16迁移和并发。预计小范围跨模块调整。部署必须先恢复库演练，再使用发布器--password-first。新增列保留可空，不删除申请或回滚已完成账号；旧应用不理解预设密码的新确认链接，不可在启用后回退旧dispatcher。

## 恢复库演练

固定候选先通过全部CI/PG16检查再合并。以下Ubuntu Bash以root执行，TARGET取本轮已审查合并SHA并与发布记录核对；真实生产代码不切换。现有auth_rehearsal_20261116应为已验收的d9，已升级则停止，不删除重建。

```bash
(
set -euo pipefail
cd /opt/mytoolbox
git fetch origin
TARGET=$(git rev-parse origin/main)
printf 'target=%s\n' "$TARGET"
STAGE=/var/lib/postgresql/password-first-registration-20261117
test ! -e "$STAGE"
install -d -o postgres -g postgres -m 700 "$STAGE"
install -d -o postgres -g postgres -m 700 "$STAGE/candidate"
git archive "$TARGET" | sudo -u postgres tar -x -C "$STAGE/candidate"
sudo -u postgres pg_dump --format=custom --file="$STAGE/database.dump" -d auth_rehearsal_20261116
sudo -u postgres /opt/mytoolbox/.venv/bin/python -c 'import hashlib,json,pathlib,sys; p=pathlib.Path(sys.argv[1]); h=hashlib.sha256(p.read_bytes()).hexdigest(); (p.parent/"manifest.json").write_text(json.dumps({"kind":"auth-rehearsal-backup-v1","files":{p.name:h}}))' "$STAGE/database.dump"
sudo -u postgres env AUTH_MIGRATION_DATABASE_URL=postgresql+psycopg2:///auth_rehearsal_20261116 /opt/mytoolbox/.venv/bin/python "$STAGE/candidate/scripts/ops/auth_registration_release.py" rehearse --password-first --writers-stopped --backup-manifest "$STAGE/manifest.json"
sudo -u postgres /opt/mytoolbox/.venv/bin/python "$STAGE/candidate/scripts/ops/verified_registration_smoke.py"
)
```

预期REGISTRATION_REHEARSAL_OK revision=e0f1a2b3c4d5，全部既有MOBILE/AUTH标志及VERIFIED_REGISTRATION_STAGING_OK通过。应用harness提交初始密码、仅确认邮件、验证欢迎邮件、原密码登录/找回重置及历史记录保持；没有真实外发或监听端口。真实浏览器邮件收件仍须生产验收。

## 生产更新

恢复库通过、固定候选CI/审查通过后，再在维护窗口执行；沿用真实的5个应用容器与两个定时器。预期源数据库d9，脚本会重新核验。确认TARGET仍是同一固定候选，不追随未知main更新。

```bash
(
set -euo pipefail
cd /opt/mytoolbox
git fetch origin
SOURCE=$(git rev-parse HEAD)
TARGET=$(git rev-parse origin/main)
printf 'source=%s\ntarget=%s\n' "$SOURCE" "$TARGET"
install -d -m 700 /root/mytoolbox-registration-release
for name in auth_registration_release.py invoice_backup.py invoice_release.py; do
  git show "$TARGET:scripts/ops/$name" > "/root/mytoolbox-registration-release/$name"
  chmod 700 "/root/mytoolbox-registration-release/$name"
done
systemctl stop auth-mail.timer
systemctl stop auth-mail.service
systemctl stop customer-project-reminders.timer
systemctl stop customer-project-reminders.service
docker stop -t 60 mindfulpenpal-ai-production-api-1 mindfulpenpal-ai-production-dispatcher-1 mindfulpenpal-ai-production-worker-1 mindfulpenpal-ai-production-deletion-worker-1 mindfulpenpal-ai-production-reference-input-cleanup-1
/opt/mytoolbox/.venv/bin/python /root/mytoolbox-registration-release/auth_registration_release.py deploy --password-first --source "$SOURCE" --target "$TARGET" --restore-verified --staging-verified
docker start mindfulpenpal-ai-production-api-1 mindfulpenpal-ai-production-dispatcher-1 mindfulpenpal-ai-production-worker-1 mindfulpenpal-ai-production-deletion-worker-1 mindfulpenpal-ai-production-reference-input-cleanup-1
systemctl start auth-mail.service
systemctl start auth-mail.timer
systemctl start customer-project-reminders.timer
systemctl is-active mytoolbox
systemctl is-active auth-mail.timer
systemctl is-active customer-project-reminders.timer
curl --fail --silent --show-error https://mindfulpenpal.com/healthz
printf '\n'
)
```

预期REGISTRATION_RELEASE_OK，revision=e0，固定release_commit、最终backup_dir，三个active及status=ok。失败停止后续操作并保留输出，不能重复迁移或清表；恢复和私下日志核验原则同[原发布故障指南](12-registration-release.md#5-故障处理与恢复)，新模式只支持d9→e0。

## 真实验收

## 当前本地验证

完整回归458项：389通过、69因PG或外部环境缺失跳过、0失败，293.692秒。之后针对三字段、确认页无密码、原密码保持、旧申请、重发/更改密码及迁移等再执行23项通过，与全量重叠。PG16新增e0迁移/失败回滚测试以及继承的全部注册并发/旧流程测试已接入CI，本地未配置PG，不能将跳过视为通过。真实e0恢复库与正式收件尚待操作员验收。

使用自己的未注册邮箱：注册页填写邮箱/密码/确认→收到新注册链接→确认页不出现密码输入→确认成功→收到注册成功邮件→原密码登录→找回密码闭环。确认原有邮箱优先申请的旧链接仍可按旧提示完成；已有账号密码不可被注册覆盖，重新提交不同密码后旧链接不可用。核对旧用户/发票/客户/等级/原件/Excel正常、专用发件人与提醒发件人正确。只反馈结果，不发送密码或邮件链接。
