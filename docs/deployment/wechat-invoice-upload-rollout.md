# 微信票据助手上线手册

状态：MVP代码候选；AppID已填 `wxe79848a64a839db8`，个人主体；服务器由操作者手动执行。没有真实微信登录、提审或正式上线结果。先按[网站留存发布](invoice-retention-rollout.md)上线e4，再发布f5手机入口；不能把未完成手机代码混入网站PR。

操作者已反馈：服务类目工具/办公，request/uploadFile/downloadFile三类域名均配置，尚未备案。继续开发/体验测试，备案与后台提审状态需跟进，尚未视为正式发布条件齐备。

请在微信公众平台的小程序备案入口按个人主体实际材料要求提交备案，身份核验仅在官方后台完成。依据[工信部APP备案通知](https://www.miit.gov.cn/zwgk/zcwj/wjfb/tz/art/2023/art_920db564162e4312916a01bed6540ad8.html)，小程序分发亦在备案范围；不能用网站已有域名备案代替小程序备案。具体微信流程见[官方备案指引](https://developers.weixin.qq.com/miniprogram/product/record_guidelines.html)及后台当日提示，正式发布前应完成备案并核验状态，不承诺审核完成时间。

## 当前验证与门禁

- 独立审查已验证绑定过期/去重冲突修复；二维码旧定时器问题已修复，待最终复核。
- 本地移动相关回归通过；隔离PostgreSQL18合成数据18项通过，包括并发重试仅一张票/一次用量、绑定码竞争、旧BLOB迁移和实际psql三段演练/错库拒绝。CI另用PostgreSQL16匹配服务器主版本；CI结果以实际PR为准。
- 上线必需：最新PR CI通过、恢复库f5升级/恢复验证、原件/历史费用对照、备份及回滚、域名DNS/TLS/现有systemd/DB/Redis/COS/防火墙/容量/监控确认。手机功能不新增Redis、COS、端口或常驻服务。
- 微信后台：个人主体当前允许的实际服务类目、备案、名称/Logo、合法域名、隐私保护指引、开发/体验成员及审核状态逐项核实。不能从“已注册”推断已可提审。

## 开发者工具导入

1. 安装/打开微信开发者工具，用小程序管理员或开发者微信登录。
2. 导入仓库 `apps/invoice-miniprogram` 文件夹，AppID与上面一致；选择小程序项目，代码原生JS，无需npm构建，无云开发。
3. 检查 `config.js` API域名为 `https://mindfulpenpal.com`（实际域名变更需同时更新后台三类域名）。生产不能勾选“不校验合法域名/TLS”。基础库选当前稳定版且不低于2.32.3；不支持隐私接口的旧微信提示升级。
4. 编译看首页，显示“手机录入暂未开放”在后端开关未开启时是预期；不能因此跳过域名校验或在客户端填AppSecret。
5. Logo源图在 `assets/logo-v1.png`。后台如要求不同尺寸/体积，按后台实际要求导出适配版本，保持方形且主体不裁切。不得把源码目录上传成服务器静态站代替微信代码上传。

## 后台与隐私准备

在微信公众平台小程序后台，分别为request、uploadFile、downloadFile配置上面HTTPS域名；不需要web-view业务域名。检查完整证书链、443可达且无跨域登录重定向，不能以开发工具跳过校验的结果代替真机。

隐私指引如实声明：微信身份仅用于登录并关联网站账户；用户主动选择的票据图片/PDF、用途/发生月/报销周期仅用于留存、打印和报销核对；文件传到本人网站账号，不采集联系人、位置或手机号，不把发票用于训练或公开展示。保留原件直到用户在网站删除，备份按实际保留策略；解绑只撤销身份和会话，不等同删除已上传票据。请填写真实运营者和联系方式以及已有备份保留时间，不能用占位文本提交。`wx.requirePrivacyAuthorize`及原生同意按钮已接入，拒绝时不能选择文件；还需后台保存并真机验证协议弹出、查看和拒绝路径。

核对来源（2026-10-28）：[官方API类型仓库](https://github.com/wechat-miniprogram/api-typings)、[类型定义](https://raw.githubusercontent.com/wechat-miniprogram/api-typings/master/types/wx/lib.wx.api.d.ts)已用于wx.login/chooseMedia/chooseMessageFile/uploadFile/隐私接口契约。官方[网络配置](https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html)与[隐私授权](https://developers.weixin.qq.com/miniprogram/dev/framework/user-privacy/PrivacyAuthorize.html)当前自动访问失败；实际类目、备案、域名保存和审核要求需登录后台核验，未宣称已核实。

## 服务器发布

### f5恢复库迁移演练

网站0.9.47已上线，操作者已确认历史金额、加油票留存选择与提取阈值/归档入口正常。先在此前独立恢复库演练手机迁移；不停止主站、不切换生产工作树、不读取生产.env、不运行微信换码。该库已完成网站业务验收且处于e4，必须保持与生产服务隔离。

`scripts/ops/mobile_invoice_rehearsal.sql`从真实f5 revision渲染，第一步严格指定测试库 `mytoolbox_invoice_verify_20261028_111850`、旧e4版本及新增对象不存在，才执行升级/降级/再升级。对所有历史用户/票据完整行及附件原件BLOB作前后指纹比较，保留已有留存/打印/月份/金额，不重置为旧默认值；约束及空摘要检查通过，最后停在f5供后续API验收。锁等待15秒、语句120秒超时，失败立即停止，不改保护重跑。生产只能正常Alembic upgrade，禁止此恢复SQL。

固定候选SHA由发布协作在评审和CI全绿后提供，按下列形式执行：

```bash
(
set -euo pipefail
cd /opt/mytoolbox
git fetch origin codex/wechat-invoice-upload
candidate=<APPROVED_MOBILE_SHA>
git show "${candidate}:scripts/ops/mobile_invoice_rehearsal.sql" > /root/mytoolbox-mobile-rehearsal.sql
chmod 0600 /root/mytoolbox-mobile-rehearsal.sql
sudo -u postgres psql -X --set=ON_ERROR_STOP=1 --host=/var/run/postgresql --port=5432 \
  --username=postgres --dbname=mytoolbox_invoice_verify_20261028_111850 \
  < /root/mytoolbox-mobile-rehearsal.sql
)
```

成功输出MOBILE_UPGRADE_OK、MOBILE_ROLLBACK_OK、MOBILE_REUPGRADE_OK和最终MOBILE_MIGRATION_REHEARSAL_OK；只反馈最终状态，不贴原件或用户明细。未见最终成功则停止手机发布。工件已独立审查、契约测试通过，本机PG18实际执行18项通过；PG16 CI及服务器执行结果以实际状态为准，不将本机结果当服务器实测。

### 正式发布边界

操作者已反馈MOBILE_MIGRATION_REHEARSAL_OK。接续用 `scripts/ops/mobile_invoice_staging_smoke.py` 对同一f5恢复库执行真实API/原件/网站同步验收：候选归档不能含.env，进程无监听、不导入生产app/config；只有微信换身份步骤被合成身份替代，不连接微信、不使用真实密钥。向恢复库新增随机测试用户及其工具授权，验证绑定、上传/原键重试只计一次、费用/公里数不变、跨期留存、普通票待确认、原件完整、Cookie/Bearer隔离、跨用户和解绑撤销。旧用户/票据/含BLOB原件行指纹必须不变。成功标记MOBILE_API_SMOKE_OK、MOBILE_HISTORY_OK、MOBILE_STAGING_SMOKE_OK。不能把此验收称为真机或真实微信登录完成。

从批准候选用git archive展开到全新的postgres专用0700目录（不复制生产.env），借用主站虚拟环境解释器、sudo -u postgres通过stdin运行该脚本，形式与网站的恢复库业务验收相同。固定候选SHA和精确命令由协作在评审/CI通过后提供；不切换生产工作树或重启服务。失败先诊断，不绕过固定库/f5版本保护重跑迁移SQL。

发布提交确定后由协作提供固定SHA命令；流程与网站相同：保留本地Caddy修改/备份，独立审查、CI、隔离恢复库迁移与业务验收，集成到develop再release PR到main。主站更新使用现有systemd，不让手机PR直接覆盖生产。

f5迁移从e4增加身份/挑战/会话/审计及上传幂等表、附件可空摘要和owner摘要唯一约束。历史NULL重复原件保留。生产先开关关闭、备份、正常Alembic upgrade到f5a6b7c8d9e0、重启并验证网站，再在服务器本机受限配置编辑器添加：

```dotenv
WECHAT_MINI_ENABLED=false
WECHAT_MINI_APP_ID=wxe79848a64a839db8
WECHAT_MINI_APP_SECRET=
```

`WECHAT_MINI_APP_SECRET`值仅在服务器本机填入，禁止复制到聊天/仓库/开发者工具。保留原有.env内容和权限0600，确认systemd实际加载来源；不要用shell命令参数传密钥、不要输出env或配置全文。后台和服务器准备好后改开关true，重启mytoolbox。成功：healthz正常、网站个人资料出现绑定入口；无凭据请求/api/mobile/bootstrap返回401，未开启时404，两者均无Cookie。缺密钥仍404，应查配置来源而非放宽鉴权。若401响应带网站会话Cookie，停止开放并排查代理/应用钩子。

## 体验版与真机验收

1. 网站登录已创建周期的测试账户，个人资料输入当前密码生成绑定二维码；在小程序内扫码或粘贴绑定码。新码使旧码失效，十分钟到期。
2. 手机拍照/相册/微信会话PDF各一张；选择周期、办事处、用途、发生月。普通票待确认、加油票仅留存，电脑同步可见，金额和公里数不变。
3. 上传中断后原条目重试，只产生一张票/一次用量；更换用途需重新选择并处理重复冲突。文件未确认保存前不要退出；退出会清空本地待上传队列。
4. 手机查看图片/PDF原件，电脑打印勾选票据；两账号不能访问对方票据。先分别验Android/iOS，临时文件名/下载PDF/隐私接口都要验证。
5. 网站解绑，手机旧会话立即401；网站账户停用、令牌过期、绑定码重放/超时均拒绝。网站其他功能正常，不在聊天贴码/令牌或真实发票。
6. 开发者工具上传体验版本、填写实际版本及说明，后台设置体验成员；体验验收通过后按后台所示提供审核测试方式。不要公开真实用户账号，审核访问只能使用隔离合成样例且无管理员权限。
7. 填写真实服务类目/隐私/备案材料，提交审核；若被拒，记录具体原因再调整。审核通过后在后台发布正式版，微信搜索或正式入口实测上述业务，并记录发布时间/版本、服务器SHA、迁移版本。审核等待或上传成功不等于已上线。

## 常见问题和回滚

- 404：开关/有效AppID/secret未就绪，或网站仍旧版；核对实际SHA和迁移，不把secret贴出来。
- 428：微信未绑定，从网站个人资料生成新绑定码。
- 401：过期/解绑/停用或Cookie污染；重新wx.login，不能让Bearer授权网站页面。
- 409：意图变更/重复绑定/并发；核对周期/用途/已有票，原意图可用原键重试。
- 413/400：20MB限制或真实格式不匹配；重选PDF/PNG/JPG，不能只改后缀伪装。
- 域名/隐私失败：后台三类域名和指引完成、基础库升级后真机重试，不关闭生产校验。
- 服务故障：先false关闭手机入口、重启确认网站可用，保留表/原件与审计；不在生产downgrade。优先前滚修复，兼容e4回滚亦须保留留存口径。完整恢复只在停写且核对可恢复备份后执行。
