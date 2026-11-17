# Gallery 与主站入口更新：人工服务器命令

## 已确认执行结果

操作员已完成“已回退服务器的恢复更新”：release_commit=31f58bc9d8620ba9633ab20e364ce354fe5c1522，main分支，home_http=200、health_http=200、active，输出UI_GALLERY_SERVER_RELEASE_OK。无需再次执行该恢复段；其中1893ad5起点断言现在会停止，这是预期保护。新备份9518327字节，archive_catalog=OK但restore_verified=NO。外网浏览器和业务账号验收仍待人工反馈。下文保留完整发布与事故恢复过程。

## 固定发布与边界

发布提交：`31f58bc9d8620ba9633ab20e364ce354fe5c1522`（PR #146）。Next 16.4.6、公开作品读取恢复、入口和文案规整已合并，Vercel由main自动构建。代码候选五组CI全部通过；真实受保护Preview的公开列表18件作品、详情、筛选、登录跳转和匿名权限检查通过。正常/过期业务身份在隔离端到端及Linux CI通过；操作员正式业务账号验收仍需完成。

本次服务器只更新Flask模板并重启mytoolbox，不执行迁移、pip/npm安装或Docker重建，不停止生成任务与邮件定时器。小程序PR145不包含在本次提交，需要另行体验验收和上传。发布授权为本轮用户明确要求更新部署；沿用用户此前允许直接合并的决定，不伪称已有非作者GitHub批准。

主站操作者为用户；Gallery构建/域名验证由助手检查。已有域名、TLS、运行服务、PG16备份恢复和邮件闭环沿用已确认环境，本次不改变数据库、Redis、COS、网络、域名或密钥。服务器容量、健康和备份仍由下面命令在执行时核对。

## 1. 服务器执行更新

### 已回退服务器的恢复更新（操作员已确认1893ad5、三个模板0644、首页和健康200）

以下针对当前已知回退状态，固定恢复到已发布Gallery对应的31f58bc。预期本地主分支仍指向之前成功快进的31f58bc；不符合即停止，不强制移动分支。备份先于切换，权限/启动/首页检查失败自动回退到原版本；只在两项本机请求和服务状态都通过后报告成功。

```bash
(
set -euo pipefail
umask 022
cd /opt/mytoolbox
SOURCE=1893ad51f6a65dc977981a26a64c6769135575d3
TARGET=31f58bc9d8620ba9633ab20e364ce354fe5c1522
test "$(git rev-parse HEAD)" = "$SOURCE"
test "$(git rev-parse main)" = "$TARGET"
test -z "$(git diff HEAD --name-only -- . ':(exclude)services/generation-service/deploy/Caddyfile.production')"
test -z "$(git diff --cached --name-only)"
test "$(systemctl is-active mytoolbox)" = active
/opt/mytoolbox/.venv/bin/python scripts/ops/invoice_backup.py
CADDY_BEFORE=$(git hash-object services/generation-service/deploy/Caddyfile.production)
rollback_on_error() {
  trap - ERR
  git switch --detach "$SOURCE"
  chmod 0644 templates/base.html templates/index.html templates/tools_base.html
  systemctl restart mytoolbox
  printf 'UPDATE_FAILED_ROLLED_BACK; do not rerun blindly\n'
  exit 1
}
trap rollback_on_error ERR
git switch main
test "$(git rev-parse HEAD)" = "$TARGET"
chmod 0644 templates/base.html templates/index.html templates/tools_base.html
SERVICE_USER=$(systemctl show mytoolbox -p User --value)
for file in templates/base.html templates/index.html templates/tools_base.html; do
  sudo -u "${SERVICE_USER:-root}" test -r "$file"
done
test "$CADDY_BEFORE" = "$(git hash-object services/generation-service/deploy/Caddyfile.production)"
systemctl restart mytoolbox
READY=0
for attempt in $(seq 1 20); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8000/healthz >/dev/null; then
    READY=1
    break
  fi
  sleep 2
done
test "$READY" = 1
curl --fail --silent --show-error --max-time 15 --output /dev/null --write-out 'home_http=%{http_code}\n' http://127.0.0.1:8000/
curl --fail --silent --show-error --max-time 5 --output /dev/null --write-out 'health_http=%{http_code}\n' http://127.0.0.1:8000/healthz
systemctl is-active mytoolbox
trap - ERR
printf 'release_commit=%s\nUI_GALLERY_SERVER_RELEASE_OK\n' "$(git rev-parse HEAD)"
)
```

预期BACKUP_OK、home_http=200、health_http=200、active、release_commit=31f58bc完整SHA及成功标志。最后在浏览器刷新正式主站并重新登录检查Gallery。模板权限检查仅作用于三个源码文件，不递归修改目录，也不改变.env、Caddy或上传数据权限。

> 事故已确认：旧命令在`umask 077`下执行Git，三个模板均变成600 root:root，服务用户无法读取。操作员恢复0644后home_http=200、health_http=200。暂停重跑旧命令；源码切换必须用022，私有备份仍用077。单独healthz成功不能作为首页恢复依据。服务器目前回退在1893ad5（detached HEAD），本节常规main更新命令不适用于该状态，不要直接重跑。

以root整块复制至Ubuntu Bash。只接受已确认的e0生产基线1893ad5或0c1f26e，已有Caddyfile本地改动保留；其他已跟踪改动、未知版本、磁盘或备份失败会停止。TARGET固定，不追随未来main。已有同版本只验证健康，不覆盖回退记录。

```bash
(
set -euo pipefail
umask 022
cd /opt/mytoolbox
TARGET=31f58bc9d8620ba9633ab20e364ce354fe5c1522
SOURCE=$(git rev-parse HEAD)
test "$(git branch --show-current)" = main
test "$(systemctl is-active mytoolbox)" = active
git fetch origin
git cat-file -e "$TARGET^{commit}"
git merge-base --is-ancestor "$TARGET" origin/main
if [ "$SOURCE" = "$TARGET" ]; then
  chmod 0644 templates/base.html templates/index.html templates/tools_base.html
  SERVICE_USER=$(systemctl show mytoolbox -p User --value)
  for file in templates/base.html templates/index.html templates/tools_base.html; do
    sudo -u "${SERVICE_USER:-root}" test -r "$file"
  done
  systemctl is-active mytoolbox
  curl --fail --silent --show-error --max-time 15 --output /dev/null http://127.0.0.1:8000/
  curl --fail --silent --show-error https://mindfulpenpal.com/healthz
  printf '\nALREADY_RELEASED\n'
  exit 0
fi
case "$SOURCE" in
  1893ad51f6a65dc977981a26a64c6769135575d3|0c1f26ec0cf211991c2c47aef3333917ec26ef04) ;;
  *) printf 'STOP: unrecognized production source=%s\n' "$SOURCE"; exit 1 ;;
esac
test -z "$(git diff HEAD --name-only -- . ':(exclude)services/generation-service/deploy/Caddyfile.production')"
test -z "$(git diff --cached --name-only)"
git merge-base --is-ancestor "$SOURCE" "$TARGET"
git diff --quiet "$SOURCE" "$TARGET" -- migrations auth models.py config.py app.py requirements.txt services/generation-service deploy
df -h /opt/mytoolbox /var/backups
/opt/mytoolbox/.venv/bin/python scripts/ops/invoice_backup.py
install -d -m 700 /var/backups/mytoolbox/ui-gallery
(umask 077; printf '%s\n' "$SOURCE" > /var/backups/mytoolbox/ui-gallery/source.sha)
(umask 077; printf '%s\n' "$TARGET" > /var/backups/mytoolbox/ui-gallery/target.sha)
CADDY_BEFORE=$(git hash-object services/generation-service/deploy/Caddyfile.production)
git branch "backup/ui-gallery-$(date -u +%Y%m%dT%H%M%SZ)" "$SOURCE"
git merge --ff-only "$TARGET"
chmod 0644 templates/base.html templates/index.html templates/tools_base.html
SERVICE_USER=$(systemctl show mytoolbox -p User --value)
for file in templates/base.html templates/index.html templates/tools_base.html; do
  sudo -u "${SERVICE_USER:-root}" test -r "$file"
done
test "$CADDY_BEFORE" = "$(git hash-object services/generation-service/deploy/Caddyfile.production)"
systemctl restart mytoolbox
systemctl is-active mytoolbox
systemctl is-active auth-mail.timer
systemctl is-active customer-project-reminders.timer
curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 2 --max-time 5 http://127.0.0.1:8000/healthz
curl --fail --silent --show-error --max-time 15 --output /dev/null http://127.0.0.1:8000/
curl --fail --silent --show-error https://mindfulpenpal.com/healthz
printf '\nrelease_commit=%s\nUI_GALLERY_SERVER_RELEASE_OK\n' "$(git rev-parse HEAD)"
)
```

预期：先BACKUP_OK（包含私有backup_dir；archive_catalog=OK不等于新备份已恢复验证），然后三个active、status=ok、固定release_commit和UI_GALLERY_SERVER_RELEASE_OK。已有恢复演练记录继续保留，本次没有结构或数据迁移，不自动恢复数据库。

执行中遇到STOP、冲突、备份失败或其他非零退出先停止；不要强制覆盖、清表或删除本地配置。版本变化前失败，服务未被停止；若版本已更新后重启/健康失败，执行下面回退。

## 2. 人工验收

主站首页工具库、客户项目和作品画廊入口正常；通用工具额度与实际配置一致，文件提示可展开。正式Gallery确认公开列表、详情、搜索筛选可用；重新登录自己的业务账号，检查公开作品、个人作品、收藏、任务入口，退出后个人接口应要求登录。不要为验收执行付费生成、删除真实作品或修改真实发票。

只反馈release_commit、active/health和验收是否通过。不要发送.env、Cookie、邮件链接、备份内容或完整日志。

## 3. 服务器回退

仅用于上述更新已切换代码、但页面或健康异常时。回到保存的原提交并重启；保留数据库新增业务记录、现有Caddy与.env。执行后处于detached HEAD，恢复下一次更新前先与负责人确认版本，不直接pull。

```bash
(
set -euo pipefail
umask 022
cd /opt/mytoolbox
SOURCE=$(cat /var/backups/mytoolbox/ui-gallery/source.sha)
case "$SOURCE" in
  1893ad51f6a65dc977981a26a64c6769135575d3|0c1f26ec0cf211991c2c47aef3333917ec26ef04) ;;
  *) printf 'STOP: rollback source invalid\n'; exit 1 ;;
esac
test "$(git rev-parse HEAD)" = 31f58bc9d8620ba9633ab20e364ce354fe5c1522
test -z "$(git diff HEAD --name-only -- . ':(exclude)services/generation-service/deploy/Caddyfile.production')"
test -z "$(git diff --cached --name-only)"
git switch --detach "$SOURCE"
chmod 0644 templates/base.html templates/index.html templates/tools_base.html
systemctl restart mytoolbox
systemctl is-active mytoolbox
curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 2 --max-time 5 http://127.0.0.1:8000/healthz
curl --fail --silent --show-error --max-time 15 --output /dev/null http://127.0.0.1:8000/
printf '\nUI_GALLERY_SERVER_ROLLBACK_OK\n'
)
```

## 4. Gallery前端回退

由负责人在Vercel提升/回退到发布前健康部署，并验证gallery.mindfulpenpal.com解析到旧构建。已记录发布前部署为`dpl_5JRekLbJDTPQZd1gLTfgGYZH2iMj`、代码0c1f26e；最终以发布时域名查询记录为准。无需恢复数据库。旧版保留原读取问题和旧Next依赖，回退仅为应急措施。
