# 发票留存与通行费分摊 API

网站前缀 `/tools/reimbursement`。沿用 Flask 签名会话和 CSRF；所属人由服务端解析，客户端不得指定 owner。小程序 API 尚未实现，不能直接把网站 Cookie 或 owner_id 当手机端授权。

## 发票

`POST /api/invoices` / `PUT /api/invoices/:id` 在原有完整表单基础上增加：

| 字段 | 契约 |
| --- | --- |
| document_kind | invoice / toll / fuel / toll_statement；后三种禁止 expense |
| inclusion_policy | expense / retain / review；新增普通发票默认 expense，其他用途默认 retain |
| occurrence_month / settlement_month | 可空 YYYY-MM，开票日仍独立 |
| amount_confirmed | boolean；expense 必须确认；新建留存票据默认未确认 |
| print_selected | boolean；新 toll 未显式传入时默认仅确认金额 ≥5 元；账单默认不打印 |

留存和待确认仍出现在列表，不进入费用汇总、封面、费用分类表或发票关联明细。修改普通发票用途时，客户端应同时设置口径。历史记录迁移为 invoice/expense/已确认/选中打印。

留存记录使用已上传且属于当前 owner 的附件。相同 owner、周期、file_url 的留存重复创建返回 200 和 `duplicate: true`，不覆盖原记录。普通成功创建返回 201。上传接口按内容复用同 owner 原件，跨用户不复用；这是顺序重试去重，当前未提供并发上传唯一性保证。删除某张发票时仍被其他记录引用的原件不会删除。

`GET /api/summary/:period_id` 返回费用统计、独立的 retained_count/review_count，以及按发生月的 toll_reconciliation（已确认账单总额、已确认零散发票总额、difference）。差额仅供核对，不自动计费。周期卡片与仪表盘金额包含派车费用且排除留存票据。

## 分摊

`POST /api/periods/:id/toll-allocation`：

```json
{"statement_id":12,"row_ids":[30,31]}
```

返回 `snapshot`、`statement_snapshot`、`total`、`rows:[{id,date,amount}]`。服务端按 ID 排序，金额数组按返回行顺序提交。仅允许同 owner、同报销周期、与账单 occurrence_month 相同的自然月派车行；账单须有原件且人工确认金额。完整正公里数作为权重，否则均分，整数分尾差落最后一行。操作替换所选行过桥费；重新分摊须包含同账单已关联的全部行。

确认提交原 statement_id/row_ids/snapshot/statement_snapshot，加 `confirm:true` 和可选 `amounts:["200.00","390.48"]`。金额非负、最多两位小数且合计严格匹配。账单或明细变更返回 409，重新预览；重复提交同快照不会重复计费。PostgreSQL 锁周期行串行化明细保存与分摊。SQLite 本地测试不能证明 PostgreSQL 并发行为。

`GET /api/periods/:id/audits`：当前 owner 最近 100 条变更，包含操作者所属人、时间、分摊前后值（仅授权者可见）。

`POST /api/periods/:id/toll-allocation/undo`，JSON `{"audit_id":42}`：当前派车数据仍与该次分摊结果一致时恢复全部原始行，记录撤销审计；有后续修改返回 409。已分摊账单须先撤销才可修改或删除。

## 打印与安全错误

周期打印只取 print_selected，与计入口径独立。上传原件限制 20MB，检查扩展名与 PDF/PNG/JPEG 内容签名。无权访问周期/票据返回 404；业务输入错误 400；数据冲突 409。新操作不返回供应商凭据或数据库错误。

## 独立评审后的数据保护补充

- `GET /api/summary/:period_id` 以及分摊、撤销、保存明细响应返回 `aux_snapshot`。`PUT /api/aux/:period_id` 在原三类明细中带 `_snapshot`，值为读取时的 aux_snapshot。服务端持周期锁后比较完整明细摘要；已有明细时缺少或过期快照均返回 409，不删除任何当前行。仅初次空明细允许省略；旧页面遇到 409 须刷新核对，不能自动重试覆盖。发票关联明细保存也锁所属周期。
- 明细响应与令牌由同一批原始行同时生成，避免两次查询之间发生提交后把旧数据配上新令牌；读取使用列值而非 ORM 缓存实体。交错提交回归验证旧响应无法覆盖新费用。
- 分摊不会覆盖关联其他账单的派车行；换账单须先撤销原分摊或选择未占用行。手动调整与保存仍有审计。
- 原件、`_thumb`、`_full` URL 按同一 file_id 判断引用，删除周期时检查全部口径，保留其他周期仍引用的原件。
- 未分类普通发票的税额仍完整计入。非零计费发票没有有效导出类别时，Excel 返回 422 中文提示，要求补齐类别，不静默丢弃金额；零金额历史凭证不受影响。
