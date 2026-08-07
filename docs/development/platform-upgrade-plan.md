# MindfulPenpal 平台升级方案（8 项需求）

> 状态：Phase 1 进行中（2026-08-07）。本文是 8 项需求的实施方案与验收标准，
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

- Provider / 模型配置中心：新增/编辑 provider、模型、启停、优先级、凭证状态
  （现有 admin-console 扩展）。
- 计分规则：模型分级（free/member）、分辨率与张数定价，存入 ai.settings 或
  专用表；工作流默认价与用户积分余额在创建任务时合并计算。
- 注册赠送积分：从环境变量改为后台运行设置（BILLING_SIGNUP_GRANT 迁移到
  ai.runtime_settings），管理员可改。

## Phase 3：会员与付费（#8）

- 用户维度：plan 字段扩展为 free / member，会员到期时间；
  免费积分（free_credits）与会员积分（member_credits）双账本。
- 付费：Stripe Checkout 订阅（已有骨架），Webhook 同步会员状态；
  会员可无限使用主站普通小工具（现有 usage limit 按 plan 放行）。
- 生图计费：免费积分只允许低阶模型（mock/free 档），会员积分允许高阶模型；
  不同模型、分辨率、张数按配置计分。
- 主站 /pricing 与 Gallery /billing 展示套餐与剩余积分。

## 安全与回滚

- 所有数据库变更幂等（先探测列/表再 ALTER），不删除旧数据。
- COS 键变更只影响新对象，旧对象继续可访问。
- 会员计费上线前需在 staging 验证 Stripe Webhook 与双账本结算。
