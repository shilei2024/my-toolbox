# 微信票据录入 API

候选实现；默认关闭。所有接口同一Flask域名。架构见[ADR-0041](../adr/0041-wechat-mobile-invoice-upload.md)，发布见[上线手册](../deployment/wechat-invoice-upload-rollout.md)。

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

| 方法/路径 | 请求 | 响应 |
| --- | --- | --- |
| POST `/session` | `{code,binding_code?}`；code为wx.login临时code | `{success,access_token,expires_at,display_name}`；未绑定428，绑定冲突409，微信换码异常503 |
| POST `/logout` | 无 | `{success:true}`，只撤销当前会话 |
| GET `/bootstrap` | 无 | `{display_name,periods:[{id,name,is_active}],offices:[{id,name}]}` |
| GET `/invoices?period_id=:id&page=1` | 仅本人周期；每页20条 | `{invoices,page,has_more}` |
| GET `/invoices/:id/file` | 仅本人票据和原件 | 原始字节、附件文件名、no-store；不签发公开URL |
| POST `/invoices` | 下面multipart | 201新建或200幂等/内容重复；`{success,duplicate,invoice}` |

票据返回字段：`id,period_id,file_name,document_kind,inclusion_policy,amount_confirmed,occurrence_month,uploaded_at,file_endpoint`。不返回微信身份、owner或客户端不需要的金额。会话256位随机、七天过期，DB只存摘要；每次鉴权检查账户启用、身份仍匹配当前AppID及用户、未撤销且未过期。

## 上传事务和失败恢复

multipart：`file`（20MB以内PDF/PNG/JPG）；`file_name`可选，微信临时路径无后缀时提供真实文件名，仍校验类型与签名；`period_id,office_id,document_kind,occurrence_month`（YYYY-MM）；`idempotency_key`（16–80位字母数字下划线连字符）。文件名去目录并限制长度/控制字符，不作为磁盘路径。周期与办事处必须属于当前用户；发生月与归属报销周期分开，可跨期留存，不按开票日或上传日自动改写。通行账单后续在桌面分摊时仍只可选择同自然月派车行。用途invoice/toll/fuel/toll_statement；不接受金额、可信URL或指定费用口径。

普通票据review，其他retain；未确认金额，加油票/普通票默认打印选中，未知过路费/账单未选中，电脑可核对修改。一个User行锁保护重试，锁后再次鉴权和检查用量。原件、票据、幂等凭证及新票用量原子提交；失败回滚，无孤立原件/扣次。相同键+意图+内容返回原票，键被复用但内容/意图不同409。相同文件新键只在相同周期、用途、发生月、办事处复用原票；不同意图409而不悄悄覆盖。已删除票据的旧键409；重新选择文件产生新键。

403/404隔离未授权资源，400参数/格式/月份错误，413体积超限，409冲突，429用量/频率限制。微信错误只返回固定说明，不回传响应体、secret或session_key。数据库并发冲突回滚后409，可原键重试。客户端本轮队列保存在内存，退出/重启后须重选；保存成功的记录和内容去重仍在服务器。
