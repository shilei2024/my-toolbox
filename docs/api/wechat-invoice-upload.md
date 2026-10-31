# 微信票据录入 API

基础上传已由操作者验收生产绑定、上传及网站同步；新增识别/确认/派车单与仪表盘为待发布能力。开关默认关闭，生产已人工启用。所有接口同一Flask域名。架构见[ADR-0041](../adr/0041-wechat-mobile-invoice-upload.md)、[ADR-0042](../adr/0042-mobile-reimbursement-entry.md)，发布见[上线手册](../deployment/mobile-reimbursement-entry-rollout.md)。

## 网站绑定接口 `/auth/mobile`

网站Cookie登录，写请求需 `X-CSRFToken`、fresh登录、JSON当前密码（不记录/存储），5次/分钟。未配置返回404，未登录401，密码错误403。

| 方法/路径 | 请求 | 响应 |
| --- | --- | --- |
| POST `/challenge` | `{password}` | `{binding_code, expires_in:600, qr_image}`；新码使旧码失效 |
| GET `/bindings` | 无 | `{bindings:[{id,created_at}]}`，不返回openid |
| DELETE `/bindings/:id` | `{password}` | `{success:true}`；撤销全部手机会话并作废未用绑定码 |

二维码直接编码一次性随机码，必须在小程序内点击扫码绑定，不是微信扫码自动打开小程序码。禁止分享二维码或码值。解绑后身份可重新绑定；旧会话仍属于原用户且已撤销。

## 移动接口 `/api/mobile`

仅 `Authorization: Bearer <access_token>`，拒绝任何Cookie；不接受owner_id；不颁发网站Cookie。只该蓝图豁免CSRF；全部响应private/no-store。未开启/配置不完整404，失效凭据401。登录限10次/分钟；上传20次/分钟且受网站报销用量限制。

手机业务API与网站报销助手共用private工具授权：管理员或明确UserToolGrant方可读写，否则403；上传等用户行锁后再次检查。网站生成绑定码也需此授权。授权撤销后不能借已有手机会话访问原件或上传；账户登录/退出、查看绑定/解绑仍可用，便于清理会话。绑定本身不授予工具权限。

| 方法/路径 | 请求 | 响应 |
| --- | --- | --- |
| POST `/session` | `{code,binding_code?}`；code为wx.login临时code | `{success,access_token,expires_at,display_name}`；未绑定428，绑定冲突409，微信换码异常503 |
| POST `/logout` | 无 | `{success:true}`，只撤销当前会话 |
| GET `/bootstrap` | 无 | `{display_name,periods:[{id,name,is_active}],offices,categories,product_lines}`，后三类为本人目录的`{id,name}`列表 |
| GET `/invoices?period_id=:id&page=1` | 仅本人周期；每页20条 | `{invoices,page,has_more}` |
| GET `/invoices/:id/file` | 仅本人票据和原件 | 原始字节、附件文件名、no-store；不签发公开URL |
| POST `/invoices` | 下面multipart | 201新建或200幂等/内容重复；`{success,duplicate,invoice}` |

票据返回字段：`id,period_id,file_name,document_kind,inclusion_policy,amount_confirmed,occurrence_month,uploaded_at,file_endpoint`。不返回微信身份、owner或客户端不需要的金额。会话256位随机、七天过期，DB只存摘要；每次鉴权检查账户启用、身份仍匹配当前AppID及用户、未撤销且未过期。

## 上传事务和失败恢复

multipart：`file`（20MB以内PDF/PNG/JPG）；`file_name`可选，微信临时路径无后缀时提供真实文件名，仍校验类型与签名；`period_id,office_id,document_kind,occurrence_month`（YYYY-MM）；`idempotency_key`（16–80位字母数字下划线连字符）。文件名去目录并限制长度/控制字符，不作为磁盘路径。周期与办事处必须属于当前用户；发生月与归属报销周期分开，可跨期留存，不按开票日或上传日自动改写。通行账单后续在桌面分摊时仍只可选择同自然月派车行。用途invoice/toll/fuel/toll_statement；不接受金额、可信URL或指定费用口径。

普通票据review，其他retain；未确认金额，加油票/普通票默认打印选中，未知过路费/账单未选中，电脑可核对修改。一个User行锁保护重试，锁后再次鉴权和检查用量。原件、票据、幂等凭证及新票用量原子提交；失败回滚，无孤立原件/扣次。相同键+意图+内容返回原票，键被复用但内容/意图不同409。相同文件新键只在相同周期、用途、发生月、办事处复用原票；不同意图409而不悄悄覆盖。已删除票据的旧键409；重新选择文件产生新键。

403/404隔离未授权资源，400参数/格式/月份错误，413体积超限，409冲突，429用量/频率限制。微信错误只返回固定说明，不回传响应体、secret或session_key。数据库并发冲突回滚后409，可原键重试。客户端本轮队列保存在内存，退出/重启后须重选；保存成功的记录和内容去重仍在服务器。

## 识别与明确确认（新增）

| 方法/路径 | 请求 | 响应 |
| --- | --- | --- |
| GET `/invoices/:id` | 本人票据 | `{invoice,snapshot}`，现有网站字段，去掉file_url；含关联明细的快照 |
| POST `/invoices/:id/recognize` | `{retry?:boolean}` | `{success,draft,snapshot,cached}`；10次/分钟，草稿不写财务字段 |
| POST `/invoices/:id/confirm` | `{snapshot,confirmed:true,...编辑字段}` | `{success,invoice,snapshot}`；20次/分钟 |

确认白名单：period_id、office_id、category_id、product_line_id、invoice_number、invoice_date、vendor、description、amount、tax_amount、total_amount、document_kind、inclusion_policy、occurrence_month、settlement_month、print_selected、remarks、customer_id、customer_level、amount_confirmed、linked_detail。未提供字段沿用原记录；类别/产品线可null，费用口径则必须补齐二者。日期ISO YYYY-MM-DD，非负金额最多2位小数且未税+税额=合计。号码/商家必填，号码64、商家255、摘要500、备注4000字以内。其余计入口径与月份规则沿用网站，不接受owner或原件URL；客户归属按当前组织目录校验。

识别复用既有百度→腾讯→Paddle链；失败不扣识别用量，成功一次扣报销用量（上传另按原有规则扣一次）。草稿存领域审计invoice.ocr，以owner+invoice_id+原件SHA复用，跨周期移动仍复用；成功缓存即使retry也不重付费，失败缓存须retry才重试。PG事务咨询锁遇同票并发返回409。识别缺字段留空，需人工补齐；success并不保证每个字段正确。确认前不改变发票和费用；确认锁后复查会话/授权与快照，过期409。已分摊账单409。关联应酬/出差明细的票面金额/日期随修改同步，单独调整过则冲突要求网站核对；仅改备注不重置手工金额/日期。客户、参与人等手机未编辑数据保留，旧客户端不提供关联明细时保留原逻辑；新表单可显式核对编辑全部应酬/出差明细。

## 首页与派车单（新增）

| 方法/路径 | 请求 | 响应 |
| --- | --- | --- |
| GET `/dashboard/:period_id` | 本人周期 | `{period_name,total_amount,invoice_count,pending_count,vehicle_count,km_total,toll_fee,parking_fee}` |
| GET `/dispatch/:period_id` | 本人周期 | `{rows,snapshot,period_name,totals}` |
| PUT `/dispatch/:period_id` | `{rows,snapshot}`，完整vehicle列表，最多1000行 | `{success,rows,snapshot,period_name,totals}`；20次/分钟 |

vehicle可编辑date、from_location、to_location、contact、km_start、km_total、toll_fee、parking_fee、product_line；返回id、自动km_end、allocated。新行id=null，已有id必须属于本周期且唯一；省略原行表示删除。真实日期、km_total必填，数字非负最多2位小数，文本≤255，产品线必须属本人目录（历史原值可保留）。服务端稳定按日期排序并承接里程，不信客户端km_end/allocated，不接收toll_statement_id等来源字段。snapshot为网站全aux快照，防覆盖其他页面改动；仅写vehicle，不重建应酬/出差。已有行ID及服务端隐藏元数据保留，已分摊行删除/修改或间接受里程链影响返回409，需先在网站撤销分摊。审计vehicle.mobile.save记录前后，失败事务回滚。

仪表盘费用取网站_summary同口径；invoice_count包括全部用途，pending_count仅金额未确认，公里/过桥/停车为派车已保存合计。金额以十进制字符串返回。四个原生tab共享进程内所选周期，清单校验所属；不自动修改网站active周期。退出/换登录清空页面缓存，上传识别中不允许退出/换期，派车未保存必须保存或明确放弃。

## 录入字段补齐（2026-10-30候选）

bootstrap新增customers（网站同一_customer_directory/_customer_dict）、customer_levels和customer_creation_enabled；categories补export_key，product_lines补code，均复用网站序列化。POST /customers接受{name,short_name,grade}，同工具Bearer授权、User锁后复查及网站_customer_creation_membership/create_customer权限与审计，201返回{success,customer}；无权403，参数无效400，10次/分钟。客户端不传组织/owner。

确认新增customer_id（可null）、customer_level（未关联客户可空/0-1/A/AA/AAA）、amount_confirmed（布尔）、linked_detail（可null或明细对象）。客户必须在当前组织有效目录中，所选客户等级由客户资料带出，客户端伪造等级无效。明细白名单为date/category/place/participants/amount/purpose/approval/location/expense_type/customer/customer_id；客户字段由服务端规范，金额非负两位小数、日期ISO或空、文本最多4000字，拒绝其他字段。按费用类别生成应酬/出差明细，显式明细依赖原票完整快照防旧覆盖；未提供新字段兼容旧客户端。新表单对齐网站可留空的发票号码/商家/日期，填日期仍校验，不改变费用计入前明确核对要求。

全部字段清单及范围见[对齐计划](../product/mobile-form-parity.md)。保留独立确认提交、旧写冲突、分摊保护、仅留存口径。移动端默认明细仅跟随原默认值，修改商家/客户不重置用户单独填写的明细金额/日期/事由。网站既有force默认联动可能覆盖手工明细，本轮不复制此缺陷，网站修复另跟踪。

## 2026-10-31 缺失金额补齐（候选）

识别及缓存响应新增可选amount_note，draft的amount/tax_amount/total_amount补缺失组件（空字符串/null/纯空白，不含显式0）。仅总额已知：amount=total_amount、tax_amount=0.00，amount_note明确暂记0须核对。两个数已知按差额/合计补第三个，不推算税率。confirm同样兼容旧客户端空白组件，在invoice.confirm审计记录amount_note；三个显式数不一致继续400，并保留Bearer登录态。不改变确认、owner、快照、费用口径。详见[规则](../product/mobile-ticket-amount-fix.md)。

## 网站账号密码登录与原件暂存（候选）

POST /api/mobile/session/password接受JSON email/password（最长255/256字符，body最多4096字节），复用网站规范化邮箱/hash、启用状态和reimbursement grant。正确返回access_token、expires_at、display_name、auth_method=password；24h Bearer，不签网站Cookie。错误/未知/禁用/无grant均通用401，结构无效400、过大413、限流429；全部no-store。IP5/min、规范邮箱摘要10/h，存储沿既有Flask-Limiter配置，memory://为每worker。修改网站密码立即使该类旧token失效；微信token不受此次密码摘要更改影响，解绑接口仍只管理微信。退出撤销当前会话，其他会话可并存。禁止客户端owner_id/AppSecret等字段。

上传occurrence_month现在可空（未确认的原件没有实际发生月），非空仍需YYYY-MM；不从当天或报销周期猜发生月。原生新上传用首页当前期、默认办事处、invoice/review与空客户/月，核对页继续完整确认。旧带月/客户/用途的客户端契约保留；幂等fingerprint及变更409不变。新客户端需新后端后再上传，否则旧后端会拒绝空月份。
