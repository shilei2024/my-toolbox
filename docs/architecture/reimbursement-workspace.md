# 报销助手（发票 OCR）架构与性能基线

## 目标与边界

报销助手是一个业务工具模块（`tools/reimbursement`），负责发票上传、OCR 回填、应酬/派车/出差
明细、报销封面与明细导出。它复用平台的登录、用量计量（`require_usage`）与限流能力，不新建
一套账户、计费或存储体系。

OCR 属于外部能力调用，按平台约束保留在模块内并以适配器形态存在（百度 → 腾讯云 → 本地
PaddleOCR），不进入共享 AI 任务队列：单张票据识别是秒级同步请求，放进队列只会增加延迟与
运维成本。

## 上传与识别流程

1. `POST /tools/reimbursement/upload` 一次读取文件，同时落盘（`uploads/reimbursement`）与
   落库（`reimbursement_attachments.content`）。落库是为了让多实例、重启后仍能按 `file_id`
   读到原件。
2. `POST /tools/reimbursement/ocr` 只接收 `file_id`，从库中取回原始字节后走识别链。
3. 识别链：百度增值税发票识别（`vat_invoice`）→ 百度通用 OCR（`general_basic`）→
   腾讯云 `VatInvoiceOCR` → 本地 PaddleOCR（未安装则跳过）→ 前端提示手动填写。

## OCR 延迟构成与优化项

单张票据的端到端耗时由四段构成：浏览器上行、服务端预处理、外部 OCR 接口、降级重试。历史
实现每一段都有可消除的浪费，优化后各段的处理方式如下。

| 环节 | 历史实现 | 现状 | 依据 |
| --- | --- | --- | --- |
| 浏览器上行 | 上传原件后，再把同一张图读成 base64 随 OCR 请求再发一次 | 只发 `file_id` | 服务端本来优先用 `file_id`，base64 完全未使用；重复上行还放大 33% 体积，弱网上行是最慢的一段 |
| 百度 token | 每次识别都换取 `access_token` | 进程内缓存到过期前 5 分钟 | token 有效期 30 天，重复换取等于每张票多付一次 HTTPS 往返 |
| HTTP 连接 | 每次调用新建连接 | 每线程复用 keep-alive 会话 | 单张票最坏会串行发起多次请求，每次都重新握手 |
| 图像预处理 | 一次性生成原图/灰度增强/强对比度三份 PNG | 惰性生成，命中即停止 | 三份大写图 PNG 编码约 0.5 s；多数票据首份即可命中，这 0.5 s 属纯浪费 |
| 增值税模板不匹配 | 继续对 3 个变体逐一尝试 | 通用 OCR 限 2 个变体 | 模板不匹配说明该票不是增值税发票，堆叠变体收益极低 |
| PDF 页数 | 最多渲染 3 页 | 最多渲染 2 页 | 增值税发票为单页，第 3 页几乎不产生字段 |
| PDF 上传预览 | 额外渲染 1600px 预览图并写盘 | 只渲染 200px 缩略图 | 前端一律用原件 iframe 展示，高清预览图无调用方 |
| PaddleOCR | 每次兜底都重新初始化引擎 | 进程内单例 | 引擎初始化要加载检测/识别/方向模型，耗时以秒计 |
| 限流 | 10 次/分钟 | 30 次/分钟 | 逐张补录的真实节奏会被原阈值误伤 |

增强版本的编码格式保持无损 PNG，不改为 JPEG：发票多为白底文字，PNG 体积更小且不引入块状
噪声，识别结果与历史版本一致。本次优化只消除无用的重复工作，不改变识别口径。

## 产品线目录维护

产品线目录（`reimbursement_product_lines`）按 owner 从 `PRODUCT_LINE_NAMES` 播种，编号由列表
顺序生成。ERP 更名时需同步三处文本：目录行、发票的 `product_line`、应酬/派车/出差明细 JSON
中的 `purpose`。三者不一致会让汇总与导出封面把该产品线落到“未匹配”分组。

`PRODUCT_LINE_RENAMES` 记录一次性更名映射（当前仅 79：物料分组 → 先楫）。`_seed_product_lines`
在读取目录时执行纠正，命中条件全部基于旧名称，因此天然幂等；目标名称已被占用时跳过并记录
告警，避免与 `(owner, name)` 唯一约束冲突。

## 生产、复用、成本与运维结论

- 生产影响：只影响报销助手的上传与识别路径，页面结构、接口契约和数据库结构不变。
- 复用：token 缓存与连接复用是通用 HTTP 细节，后续模块接入同类 OCR/审核服务时可直接沿用；
  不做成共享服务，因为它没有跨模块的状态或调度需求。
- 成本：调用次数不变，仅在“模板不匹配”路径上减少无效调用，OCR 账单略降；CPU 与磁盘 IO 下降。
- 新手部署：普通代码发布 + 重启进程，无迁移、无新增环境变量、无新云资源。
- 长期架构：外部 OCR 仍由模块适配器隔离，平台的服务注册、计费与审计边界不变。

## 验证与回滚

1. `pytest tests/test_reimbursement_ocr.py tests/test_reimbursement_manager.py tests/test_tencent_ocr_signing.py`
2. 上传一张增值税专票、一张火车票、一张扫描版 PDF，确认字段回填与降级顺序正常。
3. 打开产品线下拉，确认 79 显示“先楫”，历史报销导出封面该分组有编号且不再落到未匹配。
4. 回滚只需恢复上一版本代码并重启。注意更名纠正已经写入数据库，回滚不会把历史文本改回
   “物料分组”；如需完全回退语义，必须在大盘确认后单独执行一次反向 SQL。


## 2026-10-28 留存、打印与账单分摊（待发布）

`reimbursement_invoices` 增加 inclusion_policy/document_kind、发生月/结算月、amount_confirmed 和 print_selected；迁移 e4f5a6b7c8d9 保留历史 expense 默认值。普通发票、零散过路费、加油票和月账单共用 owner、附件、周期。后两类核对票据不冲减实际公里；仅确认后的账单金额从派车行计入。

`tools/reimbursement/retention.py` 保存独立的金额/月校验与整数分分摊；manager 提供同 owner 同周期同自然月的预览/确认/撤销。周期行锁与快照在 PostgreSQL 上避免过期覆盖，`reimbursement_audits` 记录分摊前后和修改操作者。已分摊账单先撤销才可修改或删除。审计模型属于报销领域，未新建平台服务或队列。

仪表盘、周期卡片、费用统计、封面和分类表共用明确口径。print_selected 仅控制打印，不删除电子件。留存票据不生成应酬/出差关联明细。提取页金额为人工确认，报销弹窗保留原有 OCR；没有新增批量 OCR 成本。上传复用同 owner 同内容原件，删除共享引用时保留附件。

原件仍本地 + 数据库 BLOB，尚未迁移 COS。大量手机上传前需要测量存储增长和恢复时长。详见[契约](../api/invoice-retention.md)、[ADR-0040](../adr/0040-invoice-retention-and-accounting.md)、[发布手册](../deployment/invoice-retention-rollout.md)。小程序通过下述独立鉴权边界接入，不把网站会话接口直接开放给微信身份。

## 微信轻量录入边界（0.9.48基础能力）

新增原生客户端 `apps/invoice-miniprogram` 通过Bearer专用 `/api/mobile` 调用现有报销业务。同一网站User/owner和原件BLOB，不直接写DB；网站资料页经密码/CSRF建立绑定，auth域管理外部身份、挑战、可撤销会话和审计。手机上传的原件、票据、幂等凭证、用量原子提交。手机不识别金额、不改变公里数；桌面继续确认口径、ZIP、分摊、Excel和打印。f5迁移兼容e4数据，开关默认关闭；[ADR-0041](../adr/0041-wechat-mobile-invoice-upload.md)和[API](../api/wechat-invoice-upload.md)为契约来源，真机/审核完成前不声称上线。

2026-10-29操作者已确认基础绑定、上传、网站同步成功，手机入口已人工启用，微信备案/正式审核尚未完成。以上“不识别”是0.9.48边界，下述新增能力仍待发布。

## 手机识别确认与派车单（新候选）

共享`recognize_original`提取既有OCR链，网站旧接口与手机均复用；`mobile_recognition`负责原件摘要草稿缓存、并发抑制、用量、明确确认及乐观快照，草稿不写发票。`mobile_dispatch`只修改现有vehicle明细，保留隐藏来源/ID并保护已分摊里程链；仪表盘仍读同一_summary。四个原生tab的context仅共享本人当期选择与未保存状态，登录仍属auth域。无新增表或迁移；新字段/约束、生产影响、成本与恢复边界见[ADR-0042](../adr/0042-mobile-reimbursement-entry.md)和[发布手册](../deployment/mobile-reimbursement-entry-rollout.md)。
