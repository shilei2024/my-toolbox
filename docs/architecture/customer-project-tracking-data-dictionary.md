# 客户项目跟进数据字典（Phase 0）

## 通用约定

- 领域对象使用 UUID；现有 `users.id` 保持整数并通过外键引用。
- 所有业务表含 `organization_id`、`created_at`、`updated_at`、`created_by_user_id`、`updated_by_user_id`。
- 可编辑聚合含非空 `version`，初值 1；可删除对象含 `deleted_at`、`deleted_by_user_id`、`delete_reason`。
- 时间为 PostgreSQL `timestamptz`，金额为 `numeric`，枚举在应用层用稳定代码并受数据库检查约束。
- 名称规范化值仅用于匹配，不覆盖用户原始显示值。

## 共享表

| 表 | 关键字段 | 约束与索引 |
| --- | --- | --- |
| `organizations` | `id`, `name`, `status`, `timezone` | `timezone` 默认 `Asia/Shanghai`；名称非空 |
| `organization_memberships` | `organization_id`, `user_id`, `roles`, `status` | 组织 + 用户唯一；停用成员不接收提醒 |
| `audit_events` | `organization_id`, `object_type`, `object_id`, `action`, `actor_user_id`, `safe_diff`, `occurred_at` | 对象 + 时间索引；差异必须脱敏且不可覆盖 |
| `notification_outbox` | `kind`, `idempotency_key`, `status`, `scheduled_at`, `attempt_count`, `next_attempt_at`, `safe_error_code` | 幂等键唯一；状态 + 计划时间索引 |
| `notification_deliveries` | `outbox_id`, `recipient_user_id`, `status`, `provider_message_id` | 发件箱 + 收件人唯一；不保存正文副本 |
| `organization_business_day_overrides` | `organization_id`, `calendar_date`, `is_working_day`, `label`, `version` | 组织 + 日期唯一；同时表达法定休息日和周末调休工作日 |

`roles` 首发可使用 PostgreSQL 文本数组或 JSON；领域权限层必须将其解析为受控稳定代码，禁止任意角色字符串直接授权。

## 客户与联系人

| 表 | 必填字段 | 可选字段/说明 |
| --- | --- | --- |
| `customers` | `id`, `organization_id`, `name`, `normalized_name`, `status`, `primary_owner_user_id`, `version` | `short_name`, `customer_code`, `group_name`, `industry`, `region`, `grade`, `address`, `notes` |
| `customer_contacts` | `id`, `customer_id`, `name`, `version` | `department`, `title`, `email`, `phone`, `is_primary`, `notes`；审计不保存敏感值明文差异 |

组织 + `normalized_name` 使用非唯一索引做重复提示，不硬阻断同名客户。软删除记录不出现在普通查询中。

## 项目聚合

| 字段 | 类型/允许值 | 规则 |
| --- | --- | --- |
| `id` | UUID | 主键 |
| `project_code` | varchar(32) | 组织内唯一，服务端生成 |
| `customer_id` | UUID | 同组织有效客户 |
| `name` / `normalized_name` | varchar(255) | 名称必填，规范名用于重复提示 |
| `product_name` | varchar(255) | 新建项目必填；旧项目迁移后可空，首次编辑时补齐 |
| `annual_usage` | numeric(18,4) | 兼容保留既有列类型；新建/编辑/导入时必须是大于 0 的整数，单位固定为 PCS |
| `stage_code` | 稳定代码 | 引用启用的阶段字典 |
| `assessment_grade` | A/B/C/D | 可空 |
| `probability_band` | 10/30/50/70/90 | 可配置显示，不做自动预测 |
| `primary_sales_user_id` | users.id | 必须是有效组织成员 |
| `next_action` | varchar(500) | 与 `next_follow_up_at` 成对必填 |
| `next_follow_up_at` | timestamptz | UTC 保存 |
| `last_meaningful_update_at` | timestamptz | 仅有效活动更新 |
| `expected_design_win_at` | date | 可空 |
| `expected_mass_production_at` | date | 量产时与实际日期至少一个存在 |
| `actual_mass_production_at` | date | 可空 |
| `close_reason_code` / `close_notes` | code/text | 失败时必填 |
| `paused_until` / `pause_reason` | date/text | 暂停原因必填 |
| `derived_from_project_id` | UUID | 可空，不复制活动历史 |
| `version` | integer | 非空且大于 0 |

推荐索引：`(organization_id, stage_code)`、`(organization_id, primary_sales_user_id, next_follow_up_at)`、`(organization_id, last_meaningful_update_at)`、`(organization_id, project_code)` 唯一，以及未删除项目上的规范名查询索引。

## 项目子对象

| 表 | 核心字段 | 关键规则 |
| --- | --- | --- |
| `project_members` | `project_id`, `user_id`, `role_code`, `is_primary`, `joined_at`, `left_at`, `notification_preferences` | 项目 + 用户 + 职责唯一；至少一名主业务 |
| `project_materials` | `project_id`, `opportunity_type`, `category_code`, `promoted_brand`, `promoted_mpn`, `mpn_pending`, `customer_part_number`, `application_position`, `machine_quantity`, `estimated_quantity`, `quantity_period`, `unit_code`, `target_price`, `currency`, `fx_rate_usd_cny`, `unit_price_usd`, `unit_price_cny_tax_included`, `price_updated_by_user_id`, `price_updated_at`, `technical_status`, `commercial_status`, `expected_mass_production_at`, `is_primary`, `idempotency_key`, `version` | `opportunity_type` 支持 Design In（design_in）、Design Win（design_win）、Evaluation（matched_opportunity）、Lost（competitive_opportunity），四类可互转；Lost 仅记录竞品信息，不要求推广品牌/型号，转出时必须补齐；`machine_quantity` 新写入值为非负整数 PCS；单价最多 5 位小数并去尾零展示；价格与汇率保存快照；TAM/SAM/SOM 实时派生（Lost 按竞品最高报价）；编辑/删除使用对象版本和软删除；项目 + 幂等键唯一 |
| `material_competitors` | `project_material_id`, `brand`, `mpn`, `distributor`, `model_pending`, `incumbent_status`, `quoted_price`, `strengths`, `weaknesses`, `confidence_level`, `observed_at`, `idempotency_key`, `version` | 品牌/型号/代理商至少一项，或明确待确认；报价最多 5 位小数；编辑/删除使用对象版本，删除带原因并软删除；物料 + 幂等键唯一 |
| `project_activities` | `project_id`, `activity_type`, `occurred_at`, `summary`, `details`, `customer_feedback`, `risk`, `decision`, `next_action`, `next_follow_up_at`, `is_meaningful`, `created_by_user_id` | 追加式记录；业务活动不可覆盖 |
| `project_comments` | `project_id`, `body`, `idempotency_key`, `created_by_user_id`, `created_at` | 追加式纯文本留言；正文最多 4000 字；项目 + 幂等键唯一；不修改项目版本或提醒快照 |
| `project_comment_mentions` | `comment_id`, `organization_id`, `user_id`, `created_at` | 评论 + 用户唯一；只允许同组织有效成员；每条评论应用层最多 10 人 |
| `project_stage_events` | `project_id`, `from_stage_code`, `to_stage_code`, `reason`, `idempotency_key`, `actor_user_id`, `approved_by_user_id`, `occurred_at` | 项目 + 幂等键唯一；追加式记录 |
| `project_status_catalog` | `organization_id`, `code`, `display_name`, `sort_order`, `stale_after_days`, `is_active`, `version` | 组织 + 稳定代码唯一；历史引用后不可删除代码 |
| `project_reminder_policies` | `organization_id`, 本地发送小时、提前/逾期/升级工作日、抄送角色、每日上限、`version` | 首切片为组织级唯一策略；默认停用；业务配置不放环境变量 |
| `project_reminder_overrides` | `project_id`, 启停、PM/FAE 可空覆盖、`version` | 项目唯一；空值继承组织，版本进入提醒幂等键；修改时取消未发送旧意图 |
| `notification_outbox` | 模块/事件/对象、幂等键、模板参数、计划/重试/领取/状态字段 | 共享通知事实；幂等键全局唯一；不保存渲染后正文或原始供应商错误 |
| `notification_deliveries` | 发件箱、用户、投递地址、状态、尝试、安全错误码 | 发件箱 + 用户唯一；停用账号不创建记录 |
| `notification_worker_heartbeats` | worker 名称、开始/完成时间、处理/失败计数、安全错误码 | 扫描和发送各一个稳定心跳，可供统一后台与告警读取 |
| `project_import_batches` | 文件名、SHA-256、识别映射、状态、总/有效/错误行数、提交/撤销时间 | 不保存原始文件；组织 + 创建时间索引 |
| `project_import_rows` | 批次、行号、规范化负载、错误、创建的客户/项目、创建版本、状态 | 批次 + 行号唯一；仅版本未变化的新增项目可撤销 |
| `project_export_policies` | 允许角色、是否包含价格、最大项目数、最大输出行数、策略版本 | 每组织唯一；默认仅管理员/业务经理；只控制客户项目导出 |
| `project_saved_views` | 个人/组织命名空间、显示名、规范化名、白名单筛选 JSON、创建人和版本 | 组织 + 命名空间 + 规范化名唯一；不保存查询语句或公开令牌 |
| `project_tags` / `tag_links` | 标签名、颜色、对象类型/ID | 组织内规范标签名唯一 |

## 默认字典

| 代码 | 显示名 | 停滞天数 | 类型 |
| --- | --- | ---: | --- |
| `evaluation` | 评估 | 14 | 活跃 |
| `initiated` | 立项 | 14 | 活跃 |
| `sampling` | 送样/验证 | 10 | 活跃 |
| `pilot_batch` | 小批 | 14 | 活跃 |
| `trial_production` | 试产 | 14 | 活跃 |
| `design_win` | 定点 | 30 | 活跃 |
| `mass_production` | 量产 | — | 终态视图 |
| `paused` | 暂停 | — | 辅助状态 |
| `lost` | 失败 | — | 终态视图 |
| `archived` | 归档 | — | 终态视图 |

默认失败原因：客户取消、客户延期、技术不通过、价格、交期/产能、认证、竞争对手胜出、原厂策略、内部资源不足、信息重复、其他。
