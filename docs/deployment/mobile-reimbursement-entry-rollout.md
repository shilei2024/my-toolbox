# 手机完整录入与四标签工作台发布

本轮为0.9.48之后的增量，基础绑定、上传、网站同步已由操作者实测。新功能仍待发布；不把合成OCR测试当实际识别效果。当前进展见[上线状态与门禁](mobile-invoice-launch-status-2026-10-30.md)；产品/风险见[计划](../product/mobile-invoice-recognition-plan.md)，契约见[API](../api/wechat-invoice-upload.md)，决策见[ADR-0042](../adr/0042-mobile-reimbursement-entry.md)。

## 发布边界及前置清单

- 操作者最新只读反馈生产代码为8cd9d31d3ee3ac9429c4ffe0da2a646042098cb1、`main`、`mytoolbox` active；运行数据库为PostgreSQL 16.14、Alembic f5a6b7c8d9e0，已跟踪改动仅既有Caddyfile。新功能无迁移、依赖或新环境变量。旧手机上传接口保持兼容，先后端再客户端。
- 检查main工作树，保留已知Caddy本机修改、.env、上传、备份，禁止reset/clean或重跑旧invoice_release/mobile_invoice_release一次性迁移工具。
- 当前实现已在develop；独立审查、Python/PG16及全仓CI通过后，对固定候选进行恢复库验收；发布PR到main后才能部署。用户已授权推进，服务器操作仍由操作者执行。
- 确认当前域名/DNS/TLS与health、systemd服务身份/代码可读、PG16/f5/容量、备份恢复、监控。Redis/COS/Generation/Gallery不新增或改配置，只确认现有服务健康；本模块仍原有BLOB+磁盘。
- 隐私指引已保存，三类合法域名已配置；个人主体备案及微信正式审核仍未完成。保留合法域名校验，AppSecret只在服务器。

## 恢复库业务验收（先执行，不停生产）

目的：在此前固定恢复库上验证新API与网站/Excel一致，保持原历史行指纹。只新建合成账号和票据，不向真实微信或OCR发送资料，无服务监听、不加载生产.env。

本轮固定业务候选是`87084ab003431f7b5b8a86956a323915019d9c59`，不能用浮动分支当验收身份。操作者已反馈该候选在隔离恢复库通过五项验收。`mobile_entry_release.py`原先只允许`1502ee0`业务祖先及文档/运维差异；现已固定为新验收候选，仍须独立审查、全套CI和生产基线复核。旧的`mobile_invoice_release.py`仅覆盖0.9.48固定基线。

```bash
(
set -euo pipefail
cd /opt/mytoolbox
git fetch origin codex/invoice-miniprogram-launch
candidate=CANDIDATE_SHA
git cat-file -e "${candidate}^{commit}"
git merge-base --is-ancestor "$candidate" FETCH_HEAD
stage_dir=$(mktemp -d /var/tmp/mytoolbox-entry-stage-XXXXXX)
git archive "$candidate" | tar -x -C "$stage_dir"
test ! -e "$stage_dir/.env"
chown -R postgres:postgres "$stage_dir"
chmod 0700 "$stage_dir"
sudo -u postgres /opt/mytoolbox/.venv/bin/python \
  "$stage_dir/scripts/ops/mobile_invoice_staging_smoke.py" "$stage_dir"
printf 'stage_dir=%s\n' "$stage_dir"
)
```

预期：MOBILE_ENTRY_SMOKE_OK、MOBILE_FORM_PARITY_OK、MOBILE_API_SMOKE_OK、MOBILE_HISTORY_OK、MOBILE_STAGING_SMOKE_OK。新增检查OCR草稿/缓存不改费用、明确确认/旧写409、客户选择上传与网站回显/重试、派车保存及网站仪表盘/实际XLS、跨用户隔离；保留原绑定/上传/原件/撤销验收。此脚本只允许postgres系统用户、固定Unix socket库mytoolbox_invoice_verify_20261028_111850及f5版本；失败停止，禁止改保护条件或在生产运行。先核实该隔离库确由生产备份恢复且状态可信；如已被其他测试修改或生产有新数据，重新设计全新受保护恢复库演练，不能把旧测试库视为当前生产快照。候选目录保留供核对，不递归清理未知路径。

## 生产更新与回滚准备

2026-10-30：操作者反馈候选87084ab003431f7b5b8a86956a323915019d9c59在隔离恢复库出现MOBILE_ENTRY_SMOKE_OK、MOBILE_FORM_PARITY_OK、MOBILE_API_SMOKE_OK、MOBILE_HISTORY_OK、MOBILE_STAGING_SMOKE_OK；历史用户、发票及原件BLOB行指纹保持不变。该SHA的7项CI通过。本轮新增客户上传及五页视觉仍待生产更新与真机验证。

发布工具实施门：生产受短维护影响；复用invoice_backup、发布互斥锁及Git子进程022；无迁移/依赖/资源，现有systemd即可维护；用实际观测的固定8cd9d31代码基线、f5版本及87084ab业务候选差异保护确保符合单体架构。发布工具顺序/故障恢复测试不改业务候选。回滚保留同一f5数据。先验证用量/配置/所有权边界，再备份和快进，运行代码用户可读、原行指纹与版本不变后启动；主站200、手机旧/新入口401。禁止执行旧一次性迁移工具。

恢复库成功后，协作核对发布PR/完整main SHA及业务差异，再给固定SHA的停写备份、代码快进、代码可读、服务启动和HTTPS+mobile401检查命令。此阶段尚未执行，不给出可误用的旧迁移脚本。

发布使用本轮`mobile_entry_release.py`，必须连同`invoice_release.py`、`invoice_backup.py`从同一批准main SHA提取到root新建0700目录。脚本限当前8cd9d31/f5与已验收87084ab业务祖先，拒绝数据库/依赖/Caddy或其他未经核对的业务差异；不会重新执行迁移。合并PR须保留87084ab祖先（普通merge commit或快进）；squash/rebase会使固定候选校验失败，必须重新评审发布方案。操作者使用下列形式（精确main发布SHA在release CI与审查后提供）：

```bash
(
set -euo pipefail
umask 077
cd /opt/mytoolbox
git fetch origin main
release=APPROVED_MAIN_SHA
test "$(git rev-parse origin/main)" = "$release"
runner=$(mktemp -d /root/mytoolbox-entry-release-XXXXXX)
for helper in mobile_entry_release.py invoice_release.py invoice_backup.py; do
  git show "${release}:scripts/ops/${helper}" > "$runner/$helper"
done
/opt/mytoolbox/.venv/bin/python "$runner/mobile_entry_release.py" "$release"
)
```

成功标记MOBILE_ENTRY_DEPLOY_OK，f5保持不变，active/HTTPS/mobile-enabled/new-routes-authenticated。失败标记MOBILE_ENTRY_DEPLOY_FAILED及受限日志路径，只反馈固定标记和阶段，不贴私有日志；停止后续操作。

停写前核对原SHA/.env/Caddy摘要与服务状态；用现有备份工具从运行服务同一配置取PG连接，私有目录保存最终数据库、配置、Git改动及原件。核对f5，不执行upgrade/downgrade；仅Git检出子进程umask022，备份/日志仍077。启动前使用实际服务用户逐项test -r新代码；本机/公网health均200，未带凭据的/api/mobile/bootstrap为401、no-store、无Set-Cookie。只反馈固定标记，不能贴.env/日志/真实发票。

失败保留备份/私有日志并反馈阶段。若代码未变、配置摘要一致可恢复旧服务；新代码失败保持停写，明确检查后才回旧已发布应用。当前8cd9d31基线使用同一f5结构；回滚不删审计/派车/原件，不用旧数据库覆盖正常新录入。小程序客户端回退到与该基线兼容的已发布版本，避免新客户端调用旧后端缺失接口。真实金额差错通过审计人工核对，独立修正，不擅自恢复全库。

应用回退演练：本轮真实临时Git测试验证`git switch --detach <旧SHA>`保留本机Caddy修改、未跟踪配置及备份。只有确认故障需回旧版本、记录当前release SHA/备份、核对.env/Caddy未变且无其他本机修改后，才运行以下代码回退；服务保持同一f5，不还原数据库。脚本失败输出并不自动授权忽略诊断直接回退。

```bash
(
set -euo pipefail
cd /opt/mytoolbox
test "$(git rev-parse HEAD)" = APPROVED_FAILED_MAIN_SHA
test -z "$(git diff --cached --name-only)"
systemctl stop mytoolbox
umask 022
git switch --detach 8cd9d31d3ee3ac9429c4ffe0da2a646042098cb1
sudo -u www-data test -r app.py
sudo -u www-data test -r auth/mobile_routes.py
systemctl start mytoolbox
systemctl is-active mytoolbox
curl --retry 8 --retry-connrefused --retry-delay 2 --fail --silent --show-error \
  --connect-timeout 2 --max-time 8 https://mindfulpenpal.com/healthz
)
```

确认health200与手机bootstrap401、no-store、无Set-Cookie，并检查网站历史数据。回退后服务器为detached HEAD，保留main的发布历史供诊断；后续先设计前滚修复，不运行要求main/SOURCE的旧发布脚本，不强制reset分支。不能以健康恢复代表业务差错已修正。

## 开发者工具与真机验收

后端验收完成后重新编译apps/invoice-miniprogram；AppID沿用现有项目，保留开发者工具本地配置。原生tab定义见[微信全局配置](https://developers.weixin.qq.com/miniprogram/dev/reference/configuration/app.html#tabBar)，tab跳转用[wx.switchTab](https://developers.weixin.qq.com/miniprogram/dev/api/route/wx.switchTab.html)；2026-10-29自动抓取官方页不可用，须以开发者工具编译和真机为准，不宣称已在线核实。

1. 首页能选本人当期，显示与网站同口径费用、待核对、公里/过桥/停车；切换到发票和派车均承接该周期。
2. 我的可扫码/粘码首次绑定、已绑定微信登录、查看账号、退出。上传识别中不能退出，派车草稿未保存须先保存或明确放弃；退出后各tab不显示旧账号资料。
3. 真实图片、PDF各一张：原件保存→识别建议→核对号码/日期/商家/未税/税额/合计、类别/产品线/归属→明确确认。确认前费用不变，确认后网站与导出一致。识别缺字段手工补齐；记录实际成功/缺失字段，不用合成mock结论代替。
4. 加油/零散过路/账单确认仍只留存，金额不叠加费用，实际公里不受票面金额影响；账单仍在网站分摊。
5. 派车新增/改/删、保存后网站及XLS正确，里程承接；网页并行修改后手机旧保存被409阻止，已分摊行修改须先网站撤销。
6. Android/iOS分别验证隐私、选图/PDF及原件预览；网络中断重试不重复上传/OCR；退出后旧下载不能弹出原件。

失败先反馈现象/固定错误，不发送真实发票、绑定码或令牌。全部完成后上传体验版、设置体验成员，再按微信后台完成备案/审核及发布；未获得后台通过状态不声称正式上线。

## 当前有效发布门禁（2026-10-31）

PR114复核后业务修复候选更新为`8e8ca491f29135c3f90178f66008cb56d0f0fdeb`，发布工具已固定此祖先。前文87084ab恢复库通过仅为历史，当前必须重新取得ENTRY/FORM_PARITY/API/HISTORY/STAGING五项成功；新候选不得沿用旧验收结果。按前文git archive固定SHA方式执行即可；fetch分支可能含后续仅发布脚本/文档提交，不应要求FETCH_HEAD等于业务候选，而应`git merge-base --is-ancestor "$candidate" FETCH_HEAD`验证可达后归档精确候选。所有生产备份、权限、配置保护和回滚条件不变。
