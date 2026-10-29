# 手机完整录入与四标签工作台发布

本轮为0.9.48之后的增量，基础绑定、上传、网站同步已由操作者实测。新功能仍待发布；不把合成OCR测试当实际识别效果。产品/风险见[计划](../product/mobile-invoice-recognition-plan.md)，契约见[API](../api/wechat-invoice-upload.md)，决策见[ADR-0042](../adr/0042-mobile-reimbursement-entry.md)。

## 发布边界及前置清单

- 生产当前be56a7aca204fdff804d8ec126223180447ff7bf、f5a6b7c8d9e0、手机开关已启用。新功能无迁移、依赖或新环境变量。旧手机上传接口保持兼容，先后端再客户端。
- 检查main工作树，保留已知Caddy本机修改、.env、上传、备份，禁止reset/clean或重跑旧invoice_release/mobile_invoice_release一次性迁移工具。
- PR到develop、独立审查、Python/PG16及全仓CI通过，再对固定候选进行恢复库验收；发布PR到main后才能部署。用户已授权部署，服务器操作仍由用户执行。
- 确认当前域名/DNS/TLS与health、systemd服务身份/代码可读、PG16/f5/容量、备份恢复、监控。Redis/COS/Generation/Gallery不新增或改配置，只确认现有服务健康；本模块仍原有BLOB+磁盘。
- 隐私指引已保存，三类合法域名已配置；个人主体备案及微信正式审核仍未完成。保留合法域名校验，AppSecret只在服务器。

## 恢复库业务验收（先执行，不停生产）

目的：在此前固定恢复库上验证新API与网站/Excel一致，保持原历史行指纹。只新建合成账号和票据，不向真实微信或OCR发送资料，无服务监听、不加载生产.env。

批准候选SHA由协作在评审/CI通过后给出；把下列CANDIDATE_SHA替换为提供的完整40位SHA，不能用浮动分支当验收身份。

```bash
(
set -euo pipefail
cd /opt/mytoolbox
git fetch origin codex/mobile-invoice-recognition
candidate=CANDIDATE_SHA
git cat-file -e "${candidate}^{commit}"
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

预期：MOBILE_ENTRY_SMOKE_OK、MOBILE_API_SMOKE_OK、MOBILE_HISTORY_OK、MOBILE_STAGING_SMOKE_OK。新增检查OCR草稿/缓存不改费用、明确确认/旧写409、派车保存及网站仪表盘/实际XLS、跨用户隔离；保留原绑定/上传/重试/原件/撤销验收。此脚本只允许postgres系统用户、固定Unix socket库mytoolbox_invoice_verify_20261028_111850及f5版本；失败停止，禁止改保护条件或在生产运行。候选目录保留供核对，不递归清理未知路径。

## 生产更新与回滚准备

恢复库成功后，协作核对发布PR/完整main SHA及业务差异，再给固定SHA的停写备份、代码快进、代码可读、服务启动和HTTPS+mobile401检查命令。此阶段尚未执行，不给出可误用的旧迁移脚本。

停写前核对原SHA/.env/Caddy摘要与服务状态；用现有备份工具从运行服务同一配置取PG连接，私有目录保存最终数据库、配置、Git改动及原件。核对f5，不执行upgrade/downgrade；仅Git检出子进程umask022，备份/日志仍077。启动前使用实际服务用户逐项test -r新代码；本机/公网health均200，未带凭据的/api/mobile/bootstrap为401、no-store、无Set-Cookie。只反馈固定标记，不能贴.env/日志/真实发票。

失败保留备份/私有日志并反馈阶段。若代码未变、配置摘要一致可恢复旧服务；新代码失败保持停写，明确检查后才回旧已发布应用。0.9.48可读同一f5及新保存记录，回滚不删审计/派车/原件，不用旧数据库覆盖正常新录入。客户端也退到0.9.48上传版，避免旧后端新客户端404。真实金额差错通过审计人工核对，独立修正，不擅自恢复全库。

## 开发者工具与真机验收

后端验收完成后重新编译apps/invoice-miniprogram；AppID沿用现有项目，保留开发者工具本地配置。原生tab定义见[微信全局配置](https://developers.weixin.qq.com/miniprogram/dev/reference/configuration/app.html#tabBar)，tab跳转用[wx.switchTab](https://developers.weixin.qq.com/miniprogram/dev/api/route/wx.switchTab.html)；2026-10-29自动抓取官方页不可用，须以开发者工具编译和真机为准，不宣称已在线核实。

1. 首页能选本人当期，显示与网站同口径费用、待核对、公里/过桥/停车；切换到发票和派车均承接该周期。
2. 我的可扫码/粘码首次绑定、已绑定微信登录、查看账号、退出。上传识别中不能退出，派车草稿未保存须先保存或明确放弃；退出后各tab不显示旧账号资料。
3. 真实图片、PDF各一张：原件保存→识别建议→核对号码/日期/商家/未税/税额/合计、类别/产品线/归属→明确确认。确认前费用不变，确认后网站与导出一致。识别缺字段手工补齐；记录实际成功/缺失字段，不用合成mock结论代替。
4. 加油/零散过路/账单确认仍只留存，金额不叠加费用，实际公里不受票面金额影响；账单仍在网站分摊。
5. 派车新增/改/删、保存后网站及XLS正确，里程承接；网页并行修改后手机旧保存被409阻止，已分摊行修改须先网站撤销。
6. Android/iOS分别验证隐私、选图/PDF及原件预览；网络中断重试不重复上传/OCR；退出后旧下载不能弹出原件。

失败先反馈现象/固定错误，不发送真实发票、绑定码或令牌。全部完成后上传体验版、设置体验成员，再按微信后台完成备案/审核及发布；未获得后台通过状态不声称正式上线。
