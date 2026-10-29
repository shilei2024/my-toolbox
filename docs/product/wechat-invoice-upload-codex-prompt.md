# 微信轻量录入入口：前置准备和完整 Codex 提示词

状态：本提示词的原生MVP已在独立分支实现，未混入网站留存发布；最新事实见[实施计划](wechat-invoice-upload-plan.md)、[API](../api/wechat-invoice-upload.md)、[上线手册](../deployment/wechat-invoice-upload-rollout.md)。真实微信登录、真机、审核及发布仍待验证，不将代码完成视为小程序上线。

## 运营者先准备

1. 在微信公众平台确认小程序主体类型、AppID、管理员及开发者权限。AppSecret 只填服务器环境变量，不发到聊天、仓库或客户端。
2. 安装微信官方开发者工具，确认自己的账号能打开对应 AppID。
3. 准备一个 HTTPS 网站/API 域名，在后台核对 request/uploadFile/downloadFile 合法域名配置和主体可用的服务类目；具体备案、隐私、审核要求以当前主体后台和官方规则为准。
4. 准备隔离 staging 数据库和附件目录，两个测试网站用户、两台测试设备，验证解绑和跨账号隔离。

## 官方契约核对清单

2026-10-28 尝试打开以下官方页面，当前联网工具无法读取内容，因此**尚未完成最新规则核实**。开发前必须在可访问环境重新核对并记录日期、文档变化，不能以第三方教程替代：

- [小程序登录](https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/login.html)
- [code2Session](https://developers.weixin.qq.com/miniprogram/dev/server/API/user-login/api_code2session.html)
- [网络能力及合法域名](https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html)
- [从会话选择文件](https://developers.weixin.qq.com/miniprogram/dev/api/media/other/wx.chooseMessageFile.html)
- [上传文件](https://developers.weixin.qq.com/miniprogram/dev/api/network/upload/wx.uploadFile.html)

## 可直接交给 Codex 的提示词

```text
你是 D:\cursor-project\my-toolbox 的长期技术负责人。请完成“微信小程序轻量票据录入 MVP”，从设计、代码、测试、文档推进到可供审核的 PR。遵守根 AGENTS.md 和 docs/README.md；先 git status、fetch 并检查实际分支和远端差异，保护已有修改。不要覆盖当前发票留存功能，不部署生产或合并 main。

先阅读 docs/product/invoice-retention-plan.md、docs/api/invoice-retention.md、docs/adr/0040-invoice-retention-and-accounting.md、docs/architecture/reimbursement-workspace.md 和 docs/deployment/invoice-retention-rollout.md。确认网站端功能所在提交已经合入你的工作基线。develop 可能落后 main，禁止把过时 develop 当作最新生产。实质变更用 codex/ 功能分支。

先回答五个 Golden Rule 问题，写明生产影响、复用、最低成本替代方案、新手部署方式和长期架构结论，列出文件/模型/API/迁移/测试/回滚计划再编码。不新建业务数据库、报销后台或重复账户系统。

第一步核验微信官方最新文档：wx.login、code2Session、chooseMedia、chooseMessageFile、uploadFile、合法域名、主体服务类目、备案、用户隐私保护指引及审核。引用官方 URL 并记录核验日期；无法访问的规则列为未验证项，不能宣称已核实。AppID、主体类型和开发者工具条件向用户询问；AppSecret 不允许在聊天中索取或展示。

MVP：登录与网站账号绑定；拍照/相册选图片、从微信会话选 PDF；选票据用途、发生月、归属报销周期；进度、失败重试、本人票据列表及待确认状态。普通发票手机上传后先待确认，禁止 OCR 未经确认就计入费用；加油票、零散过路费、通行账单默认 retain。复用现有 document_kind/inclusion_policy/amount_confirmed/print_selected，不能把金额置空当作费用排除逻辑。加油票不冲减公里数。

ZIP 递归解压、金额阈值筛选、账单分摊、Excel 导出和批量打印继续在网站完成；手机不处理 ZIP，不引入新队列或常驻服务。

身份设计：网站用户在已有登录态下通过受 CSRF 保护的接口生成至少 128 位随机短期一次性绑定令牌，数据库只保存摘要、到期时间、使用记录和操作者。新绑定令牌使旧令牌失效，频率限制；过期、重放、两台设备并发消费要测试。

小程序 wx.login 的临时 code 只发到本站服务端；服务端调用 code2Session（超时、错误脱敏，不日志记录完整请求 URL），AppSecret/session_key 只留服务端；无需解密业务数据时不保存 session_key。openid 仅作该 AppID 下微信身份索引，不作为本站用户 ID 或授权凭证。

绑定必须同时校验网站一次性令牌及服务端取得的微信身份。用户映射只能由服务端建立。已绑定其他网站账号不得静默换绑；网站重新验证身份后显式解绑才可重绑。解绑立即吊销该绑定所有移动令牌，记录审计；新设备登录和网站用户停用要即时检查。不要自动迁移匿名历史数据或凭手机号/owner_id 认领数据。

移动端使用服务端生成的随机短期 Bearer 令牌，数据库只存摘要、到期时间、撤销状态；令牌不得出现在 URL、错误、日志或数据库明文中。定义失效后重新 wx.login 的流程。独立受控移动 API 只接受有效 Bearer，不能仅因同请求带网站 Cookie 就跳过授权；CSRF 豁免必须严格限定这些 Bearer-only 路由，不全站关闭 CSRF。不要把微信身份拼进 existing owner_id。

业务复用：从现有 manager 中适量提取可调用的发票业务服务，让网站和手机 API 走同一套权限、周期校验、存储和口径，不复制保存/统计逻辑，不绕过 require_usage/限流。客户端不传可信 owner_id、不直接写数据库、不持 COS 长期密钥。跨用户/周期访问返回脱敏 404。

移动上传须有文件大小/签名/扩展名校验、用户与 IP 限流、所有权检查、摘要去重，以及同一次上传重试的唯一幂等键（PostgreSQL 唯一约束和事务保证）。返回成功只有附件与票据记录均持久化后才允许；失败不生成悬空计费记录。测试并发重试、网络超时、非法文件、OCR 失败、越权、令牌过期/撤销。

沿用附件存储实现 MVP，先评估本地+DB BLOB 容量、备份体积与恢复时间。若必须迁 COS，经存储适配层保持旧附件可读，单独 ADR 和迁移/回滚，不在小程序接入中偷换生产存储。

配置默认关闭：没有 AppID/AppSecret 不影响网站现有能力。新增业务模型放对应 domain/auth 包，迁移向后兼容；明确开启顺序和关闭回退方案，不在 Flask 启动时偷偷迁移数据库。新手文档给出精确的变量名称、后端命令、合法域名填写步骤、开发者工具导入目录、隐私配置、真机验证、体验版、审核、发布、回滚步骤和预期结果。

至少写有意义的服务端鉴权/绑定/去重/隔离测试与小程序请求状态测试，运行相关 Python 全量回归和 JS 检查；在 PostgreSQL 恢复库验证 migration 和并发。不改无关 Gallery/生成服务。更新 docs/product、architecture、api、adr、deployment 及根 CHANGELOG。

验收：手机上传的票据能在同账号网站同周期出现；电脑确认后金额/打印/分摊保持一致；加油票和小额票不会误计金额；跨用户无读取；解绑后旧设备立刻失去访问。交付文件清单、实际通过的测试、未验证项、可审查 PR 和上线前检查清单。没有真实 AppID/真机/官方审核时明确标为未验证，不能宣称小程序已上线。生产发布须独立评审、CI、隔离 staging、备份恢复演练与发布批准。
```
