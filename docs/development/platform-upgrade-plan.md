# MindfulPenpal 平台升级方案（8 项需求）

> 状态：Phase 2 完成（2026-08-07）。本文是 8 项需求的实施方案与验收标准，
> 按阶段落地，每阶段完成后更新本文件。

## 需求与现状对照

| # | 需求 | 现状 | 方案 |
| --- | --- | --- | --- |
| 1 | 主站 AI 作图入口卡片（生图 + 画廊） | 首页 ai_image 只是普通外链卡片 | 首页顶部设计科技感 Hero 卡片，突出“AI 生图 / 画廊展示”，链接 Gallery |
| 2 | 主站与 Gallery UI 统一、科技感 | 两套独立 Bootstrap / Tailwind 样式 | 建立共享设计令牌（渐变、圆角、网格背景、字体），两站同步使用 |
| 3 | 后台：模型配置、积分设置、删除用户、注册赠送积分 | Provider 增删/启停已有；积分/删除/注册赠送不完整 | 后台用户管理增加积分调整与删除；Provider/模型/计分规则管理做成配置中心；注册赠送接入运行设置 |
| 4 | COS 按用户名归档 | 对象键为 images/jobs/{jobId}/… | 新上传键改为 images/{用户名}/{jobId}/…，保留旧对象不动 |
| 5 | 昵称（默认显示注册账号，全部作品冠名） | 无昵称；画廊显示 ai.user_profiles.display_name | users 增加 nickname；未设置时显示 email；设置昵称同步 ai.user_profiles |
| 6 | 生图结果按所选尺寸居中展示 | 预览区有 aspect-ratio 但未严格居中/约束 | 预览容器居中、按实际宽高比显示、附尺寸标注 |
| 7 | 统一网站小图标 | 主站 SVG 与 Gallery ico 不一致 | 设计同一科技风图标（渐变 M + 星芒），两站共用 |
| 8 | 会员与付费 | 仅有 plan 字段与 Stripe 骨架 | 会员订阅 + 双积分账本（免费/会员）+ 模型分级计分 + 工具无限使用 |

## Phase 1（当前批次）：基础体验与数据整理

1. **昵称（#5）**：users.nickname 字段（幂等迁移）；`/profile` 设置页；头部显示
   昵称或邮箱；Gallery session 返回 nickname；画廊创作者冠名同步
   ai.user_profiles.display_name。
2. **统一小图标（#7）**：设计同一 SVG（渐变 M + 星芒），主站
   `static/img/favicon.svg`、Gallery `app/icon.svg` 与 `app/favicon.ico`。
3. **生图预览居中（#6）**：预览容器按实际尺寸约束并居中，标注宽高。
4. **AI 入口卡片（#1）与科技风基础（#2）**：首页 Hero 卡片；两站共享设计令牌
   （主色渐变 #6d5cff → #22d3ee、玻璃卡片、网格背景）。
5. **COS 按用户名归档（#4）**：对象键 `images/{用户名}/{jobId}/{序号}`，
   存量对象不受影响；更新桶策略文档。
6. **后台用户管理（#3 部分）**：昵称设置、积分调整（ai.credit_accounts）、
   删除用户（软删除：停用 + 邮箱匿名化，保留审计）。

验收：主站与 Gallery 均可打开；新用户设置昵称后主站/画廊/作品署名一致；
新生成图片对象键带用户名；后台可调积分、删除用户。

## Phase 2：后台配置中心与积分规则（#3 完整）

**已完成（0.7.0）**：
- 模型配置中心：Gallery 后台新增模型与计分面板（tier/单张积分/默认/启停），
  后端 `PATCH /v1/admin/provider-models/:id`；
- 计分规则：工作流 `defaults.pricing` 按尺寸定价 × 张数；
- 注册赠送积分：主站后台可配（public.settings），Generation Service 优先读库；
- 模型分级 gating：free 档任务仅可用 free 模型。

**待办**：
- Provider 凭证在后台直接更新（当前只显示“已配置”状态）；
- 新 Provider/模型的可视化新增（当前需代码适配器 + SQL 种子）。

- **模型配置中心**：扩展现有 admin-console——
  - Provider：新增/编辑（代码内已有适配器的才可新增，避免产生死路由）；
    启停、优先级、凭证状态（可粘贴/更新密钥，只显示“已配置”）。
  - 模型：`ai.provider_models` 增加 `tier`（free/member）与 `credit_cost`；
    行内编辑 model_code、默认模型、启停。
- **计分规则**：`ai.workflow_versions.defaults` 增加 per-size 定价表
  （如 `{"1024x1024":1, "1920x1920":2, ...}`）+ 张数倍率；创建任务时按
  尺寸×张数预留，worker 结算时按实际模型 tier 从对应账本扣费。
- **注册赠送积分后台可配**：主站 `public.settings` 增加
  `signup_credit_grant`；Generation Service 读取同一数据库的该配置，
  优先于环境变量 `BILLING_SIGNUP_GRANT`。
- 管理入口：主站后台 → 设置页新增“积分与模型”分组；Gallery 后台
  admin-console 增加模型/计分标签页。

## Phase 3：会员与付费（#8）

**已完成基础（0.7.1）**：
- 双积分账本：ai.member_credit_accounts + 流水 account_type；任务按 credit_tier
  从对应账本预留/结算/释放。
- 积分兑换码：后台批量生成，Gallery 账单页兑换到会员账本（国内支付第一步）。
- 创作页积分档位选择（免费/会员）；free 档仅可用 free 模型。

**待办**：
- 微信支付 Native / 支付宝电脑网站支付（需商户资质）；
- 订阅会员（subscription）与会员到期自动降级；
- 兑换码购买页（微信/支付宝收款码 + 填码）合并进 /pricing。

- 用户维度：plan 字段扩展为 free / member，会员到期时间；
  免费积分（free_credits）与会员积分（member_credits）双账本。
- **国内支付路径（按资质分档）**：
  1. 有营业执照/个体户：微信支付 Native（PC 扫码）+ 支付宝电脑网站支付；
     适配层 `billing/payment-provider.ts` 增加 wechat/alipay 实现，
     回调验签后同步会员与积分。
  2. 暂无商户资质：先上线“积分兑换码”（管理员在后台生成兑换码/充值码，
     用户提交后人工/自动核销），微信/支付宝转账后填码即可到账；
     同时保留 Stripe 国际卡作为海外兜底。
  3. 后续接入第三方聚合（如虎皮椒）需评估合规与费率，默认不推荐。
- **会员权益**：会员可无限使用主站普通小工具（现有 usage limit 按 plan
  放行）；生图仍按积分计费。
- **双账本**：`ai.credit_accounts` 拆分为两行（account_type=free/member），
  保留现有 ledger 审计；免费积分只能调用 tier=free 的模型，会员积分可调用
  tier=member 模型。
- 生图计费：免费积分只允许低阶模型（mock/free 档），会员积分允许高阶模型；
  不同模型、分辨率、张数按配置计分。
- 主站 /pricing 与 Gallery /billing 展示套餐与剩余积分。

### 2026-08-07 追加：报销发票 OCR 修复
- 根因：未配置任何可用 OCR 后端（百度密钥缺失、PaddleOCR 未安装），
  接口永远返回“模拟降级”空结果。
- 修复：新增腾讯云增值税发票识别适配器（TC3 签名，复用腾讯云密钥，
  无新增 SDK），识别顺序改为 腾讯云 → 百度 → PaddleOCR → 模拟降级。

## 安全与回滚

- 所有数据库变更幂等（先探测列/表再 ALTER），不删除旧数据。
- COS 键变更只影响新对象，旧对象继续可访问。
- 会员计费上线前需在 staging 验证 Stripe Webhook 与双账本结算。
