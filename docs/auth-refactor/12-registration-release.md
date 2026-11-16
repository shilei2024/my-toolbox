# 邮箱验证注册闭环：更新与人工验收

目标 revision：`d9e0f1a2b3c4`，只接受已在 `c8d9e0f1a2b3` 的数据库。正式域名 `https://mindfulpenpal.com`。本文步骤必须按顺序完成；目前真实环境仍是已部署的旧注册行为，不能仅更新Python文件而跳过迁移。

## 1. 发布条件

固定候选须通过审查、全部CI和PG16并发/迁移测试，再合并main。操作员已有的独立 `auth_rehearsal_20261116` 恢复库可用于本轮演练；先确认其仍是c8，并做本轮新备份，不能只使用最初f5的dump作为回退点。演练只写恢复库的合成账号，无真实SMTP/微信/OCR调用。

原有专用发件配置及真实SMTP应已验证可用；AUTH_MAIL_ADAPTER不得为disabled。新用户注册完全依赖验证邮件，SMTP未就绪时注册页应明确503而不创建申请或用户。既有提醒发件凭据不变。继续沿用[生产环境检查](10-release-runbook.md#1-发布前条件)，尤其共享限流存储、TLS、磁盘、备份、监控和所有写者的维护窗口。

## 2. 在服务器准备独立候选

以下Ubuntu Bash命令以root执行；TARGET必须是**已审查且CI通过的本轮合并SHA**。从main取值后与本轮发布记录核对，不追随未经核对的浮动更新。整段在子shell中执行，失败会停止。

```bash
(
set -euo pipefail
cd /opt/mytoolbox
git fetch origin
TARGET=$(git rev-parse origin/main)
printf 'target=%s\n' "$TARGET"
STAGE=/var/lib/postgresql/verified-registration-20261116
test ! -e "$STAGE"
install -d -o postgres -g postgres -m 700 "$STAGE"
install -d -o postgres -g postgres -m 700 "$STAGE/candidate"
git archive "$TARGET" | sudo -u postgres tar -x -C "$STAGE/candidate"
sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d auth_rehearsal_20261116 -c 'SELECT version_num FROM public.alembic_version;'
sudo -u postgres pg_dump --format=custom --file="$STAGE/database.dump" -d auth_rehearsal_20261116
sudo -u postgres /opt/mytoolbox/.venv/bin/python -c 'import hashlib,json,pathlib,sys; p=pathlib.Path(sys.argv[1]); h=hashlib.sha256(p.read_bytes()).hexdigest(); (p.parent/"manifest.json").write_text(json.dumps({"kind":"auth-rehearsal-backup-v1","files":{p.name:h}}))' "$STAGE/database.dump"
sudo -u postgres env AUTH_MIGRATION_DATABASE_URL=postgresql+psycopg2:///auth_rehearsal_20261116 /opt/mytoolbox/.venv/bin/python "$STAGE/candidate/scripts/ops/auth_registration_release.py" rehearse --writers-stopped --backup-manifest "$STAGE/manifest.json"
sudo -u postgres /opt/mytoolbox/.venv/bin/python "$STAGE/candidate/scripts/ops/verified_registration_smoke.py"
)
```

预期先打印原revision=c8，随后 `REGISTRATION_REHEARSAL_OK revision=d9e0f1a2b3c4`。最后包含全部既有 MOBILE_* / AUTH_* 业务标志以及 `VERIFIED_REGISTRATION_OK`、`VERIFIED_REGISTRATION_STAGING_OK`。工具使用真实HTTPS/CSRF表单和内存邮件捕获，覆盖申请、待验证无用户、完成验证、欢迎、登录、找回、重置、旧会话失效及新密码登录。除只为合成账号派发的任务外，全部原有public表记录摘要应保持，新增合成数据不应按旧总量判断失败。

若目录已存在、库已升级、任何检查失败，停止并反馈安全标志，不删除恢复库重跑。保留本轮c8备份，必要时将其恢复到另一个新隔离库后另行适配固定名称；不能覆盖唯一生产库。这个演练不代替正式浏览器与真实收件验收。

## 3. 生产升级

先完成第2节。将三个部署文件从本轮固定TARGET导出到工作区外；SOURCE记录当前真实生产SHA。脚本要求main、SOURCE准确、TARGET匹配已fetch的origin/main、可快进，除既有Caddy外无跟踪改动且无暂存改动，依赖和代理未变。

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
/opt/mytoolbox/.venv/bin/python /root/mytoolbox-registration-release/auth_registration_release.py deploy --source "$SOURCE" --target "$TARGET" --restore-verified --staging-verified
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

预期 `REGISTRATION_RELEASE_OK`、revision=d9、release_commit固定SHA、新的backup_dir、三个active和健康status=ok。生产脚本停止主站后做最终备份、保留.env/Caddy、快进、同事务迁移和全部既有public表摘要核对，再启动网站及健康检查。这里使用的是操作员已核对的实际Docker容器名；如部署拓扑变化，先重新盘点，不照搬停止其他项目。

## 4. 真实验收

1. 使用自己可收件且未注册的邮箱，从/register申请；看到明确待验证页，没有业务登录。
2. 查收“验证邮箱，完成注册”邮件。打开链接只展示设置密码页；提交密码后显示注册成功，收到“注册成功”邮件。
3. 用新密码登录，网站正常，且未获得管理员或私有工具权限。微信注册仍按原规则立即获得发票助手。
4. 退出后从/account/recover申请邮件，完成重置；旧网站/移动会话退出，新密码能登录。
5. 过期链接进入重发引导；一分钟冷却与限流正常；重复点击不会新增用户。旧账号登录可见邮箱验证提示，验证后自助找回；旧账号忘记密码且邮箱从未验证，使用管理员恢复入口。
6. 既有发票、客户、等级、原件和Excel正常；确认账号安全发件人与项目提醒发件人各自正确。

不要把邮件token、链接、密码或完整日志发到聊天。只反馈成功标志、发件人是否正确和哪个步骤失败。

## 5. 故障处理与恢复

- `REGISTRATION_RELEASE_FAILED`：停止后续步骤。若已进入迁移/切换阶段，主站保持停止，不能启动不匹配的旧代码；私下核对release.log和revision，修复后前进。
- 原有数据变化会使迁移事务整体回滚；保持备份，排查是否仍有写者。不要删表、改revision或跳过摘要检查。
- 邮件任务有failed/pending：检查定时器、SMTP专用凭据、服务商限制与收件垃圾箱。注册申请不是正式账号，重发不会替换已有账号；欢迎失败不会取消完成的注册。
- 结构已升级但没有新任务时旧应用仍可读既有字段；产生register/welcome新任务后禁止运行旧dispatcher。不要用降级迁移删除申请、任务或已完成用户。
- 灾难恢复遵循已演练备份恢复到新库、匹配代码、完整业务对账与备份后新增写入保全；禁止直接覆盖唯一生产库。

监控新申请数量/完成率、队列失败与等待时长、定时器、注册/重发429和数据库容量；当前不自动清理注册映射与安全审计。
