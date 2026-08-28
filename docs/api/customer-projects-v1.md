# Customer Projects API v1（Phase 1–3 契约）

> 状态：Phase 1 核心台账、Phase 2 提醒闭环与 Phase 3 生命周期首切片已实现，功能开关默认关闭，尚未部署生产。Phase 2 提醒通过统一后台和服务器 CLI 管理，不新增浏览器公开触发端点。

## 通用边界

前缀为 `/api/v1/customer-projects`，仅接受主站登录会话；写请求同时要求 CSRF、同源检查、有效组织成员和对象级权限。客户端不得提交可信的 `organization_id` 或操作者 ID，均由服务端会话推导。当前页面端已支持项目基础信息编辑，复用同一版本控制规则。

请求和响应使用 UTF-8 JSON。单页默认 25、最大 100 条；批量请求最大 100 项且限制总请求体。日期时间使用 ISO 8601 UTC。列表游标为服务端签名的不透明字符串。

## 端点

| 方法 | 路径 | 说明 | 并发/幂等 |
| --- | --- | --- | --- |
| GET/POST | `/projects` | 项目列表/创建 | POST 使用 `Idempotency-Key` |
| GET/PATCH/DELETE | `/projects/{project_id}` | 详情、更新、软删除 | PATCH/DELETE 使用 `If-Match` |
| POST | `/projects/{project_id}/activities` | 新增不可覆盖的跟进 | `Idempotency-Key` |
| POST | `/projects/{project_id}/stage-transitions` | 状态变化/审批 | `Idempotency-Key` + 当前版本 |
| POST | `/projects/{project_id}/reactivate` | 经理将暂停/终态项目恢复到进行中阶段 | `Idempotency-Key` + `project_version` |
| POST | `/projects/{project_id}/derive` | 创建独立生命周期并按选择复制成员/物料/竞品 | `Idempotency-Key` |
| POST | `/projects/{project_id}/materials` | 新增物料，可同时录入单机数量和单价 | `Idempotency-Key` |
| PATCH/DELETE | `/materials/{material_id}` | 更新物料主数据/商务字段，或带原因软删除 | `If-Match`；仅业务/PM 价格角色可改价格 |
| POST | `/materials/{material_id}/competitors` | 新增竞争方案 | `Idempotency-Key` |
| PATCH/DELETE | `/competitors/{competitor_id}` | 更新竞争方案，或带原因软删除 | `If-Match` |
| POST | `/trash/projects/{project_id}/restore` | 管理员恢复软删除项目 | 组织与角色校验 |
| GET | `/reports/lifecycle` | 当前量产/失败/归档快照和明细 | 与项目列表相同的数据范围 |

项目更新允许修改名称、产品名称、项目年用量、评估等级、概率档位、下一步、下次跟进时间、预计定点日期和预计量产日期；仍必须通过 `If-Match` 携带当前版本。新建项目要求 `product_name` 和大于 0 的整数 `annual_usage`（PCS），兼容迁移前的旧项目记录可暂时返回 `null`。

客户/联系人在 Phase 1 通过服务端页面提供；其稳定 JSON CRUD 和通知查询 API 仍属后续切片。未实现端点不返回伪成功。

## 生命周期请求

重新激活仅允许组织管理员或业务经理调用，来源状态必须是 `paused`、`mass_production`、`lost` 或 `archived`，目标必须是进行中阶段。请求必须提供 `reason`、`next_action`、`next_follow_up_at`、`project_version`，可提供新的 `primary_sales_user_id`。成功追加阶段事件并递增项目版本，不清除既有复盘字段和历史。

衍生请求使用正常新建项目必填字段，并可提交布尔值 `copy_members`、`copy_materials`、`copy_competitors`。新项目返回 `derived_from_project_id`；客户默认沿用来源项目，活动与阶段事件绝不复制。`copy_competitors=true` 仅在同时复制物料时生效。当前领域尚无项目标签实体，因此“复制标签”不伪实现，留待标签模型正式落地。

## 乐观锁

详情响应返回 ETag 和 `version`：

```http
ETag: "7"
```

更新必须发送：

```http
If-Match: "7"
```

版本冲突返回 409，并提供服务器最新版本与允许安全回显的当前值；服务端不自动合并。

## 创建项目示例

```json
{
  "customer_id": "f34214b0-e929-47d1-9d2d-7e0a45e78ee7",
  "name": "车载电源控制器",
  "product_name": "48V 域控制器",
  "annual_usage": "120000",
  "stage_code": "evaluation",
  "primary_sales_user_id": 42,
  "next_action": "确认原理图和样品数量",
  "next_follow_up_at": "2026-09-01T01:00:00Z",
  "assessment_grade": "B",
  "materials": []
}
```

成功返回 201、资源 URL、ETag 和服务器生成的 `project_code`。同一幂等键及相同请求摘要重试返回原结果；同键不同摘要返回 409。

## 物料商务信息

`POST /projects/{project_id}/materials` 和 `PATCH /materials/{material_id}` 接受：

```json
{
  "opportunity_type": "matched_opportunity",
  "machine_quantity": "2",
  "unit_price": "1.25",
  "currency": "USD"
}
```

`opportunity_type` 支持 `design_in`（Design In）、`design_win`（Design Win）、`matched_opportunity`（Evaluation）和 `competitive_opportunity`（Lost）。四类可互转；Lost 仅记录竞品信息，创建/转入时不要求推广品牌与型号，转出为其他三类时必须补充推广品牌与型号（或勾选型号待确认）。物料响应增加 `annual_value_usd`：普通物料按项目年用量 × 单机数量 × `unit_price_usd` 计算，Lost 物料按竞品最高报价计算；缺少任一因子时返回 `null`。项目页面的 TAM 为四类总和（Lost 按竞品报价），SAM 为 Design In + Design Win + Evaluation，SOM 为 Design In + Design Win，均为实时派生值而非持久化字段。`POST /materials/{material_id}/competitors` 的 `quoted_price` 在创建时即可填写。

`machine_quantity` 为空或非负整数，单位固定为 PCS。`unit_price` 与竞争方案 `quoted_price` 最多接受 5 位有效小数；多余末尾 0 不计入位数。API 的数量返回整数字符串，价格返回最多 5 位且不带末尾 0 的字符串。

`currency` 仅支持 `USD` 或 `CNY`。USD 输入视为未税美元，服务端按主站 USD/CNY 汇率乘以 `1.13` 得到含税人民币；CNY 输入视为已含 13% 增值税，再反算未税美元。响应同时返回 `unit_price_usd`、`unit_price_cny_tax_included`、`fx_rate_usd_cny` 和原始录入币别。服务端保存折算快照，后续汇率变化不会修改历史单价。

价格写入只允许组织管理员、业务经理、`sales` 和 `pm`；FAE 可以更新 `machine_quantity`，也可以查看折算结果，但提交 `unit_price` 返回 403。汇率服务不可用且无缓存时，价格不保存并返回 422；客户端预览只用于展示，最终结果以服务端计算为准。

物料 PATCH 还可更新 `category_code`、`promoted_brand`、`promoted_mpn`、`mpn_pending`、`customer_part_number`、`application_position`、`technical_status`、`commercial_status`、`expected_mass_production_at`、`is_primary` 和 `notes`。竞争方案 PATCH 可更新创建时的业务字段以及 `quoted_price`、优劣势、置信度和观察日期。两类更新都必须携带当前 ETag；DELETE 必须同时携带 ETag 和非空 `reason`，仅写入软删除状态与审计，不物理清除历史。

页面端提供 `GET /customer-projects/projects/export.xlsx`，按当前用户的数据范围以及 `q`、`stage` 筛选导出项目、客户评级、物料数量和双币单价。该页面导出写入审计事件；当前不作为稳定 JSON API 承诺。

## 新增跟进示例

```json
{
  "activity_type": "meeting",
  "occurred_at": "2026-08-27T06:30:00Z",
  "summary": "确认首轮送样计划",
  "details": "客户需要两种封装进行温升测试",
  "is_meaningful": true,
  "next_action": "准备两种封装各 20 片",
  "next_follow_up_at": "2026-09-03T01:00:00Z",
  "project_version": 7
}
```

该请求在一个事务中追加活动、更新项目快照、递增项目版本、写审计并取消尚未发送的旧提醒意图。

## 时间线留言与 @

`POST /projects/{project_id}/comments` 需要写权限和 `Idempotency-Key`：

```json
{
  "body": "请协助确认客户测试结论。",
  "mention_user_ids": [42, 57]
}
```

正文必填且最多 4000 字；每条最多提及 10 名当前组织有效成员。留言是独立追加记录，不递增项目版本、不修改下一步或跟进时间，也不自动发送通知。响应返回评论 ID、作者、提及成员 ID 和创建时间；同键同内容重试返回原记录，同键不同内容返回 409。

## 统一错误

```json
{
  "error": {
    "code": "PROJECT_VERSION_CONFLICT",
    "message": "项目已被其他成员更新，请刷新后重试。",
    "field_errors": {},
    "request_id": "req_01K...",
    "details": {"current_version": 8}
  }
}
```

稳定状态码：400 输入格式、401 未登录、403 无权限、404 不存在或不可见、409 版本/幂等冲突、413 请求过大、422 业务规则不满足、429 限流、500 安全通用错误。跨组织对象统一返回 404，避免枚举。

## 报表响应元数据

生命周期报表支持 `date_from`、`date_to`、`year`、`month`、`customer_id`、`owner_user_id`、`stage`、`material_brand`、`category`、`competitor_brand` 和 `distributor`；日期筛选基于项目 `updated_at` 的 UTC 自然日。响应带 `generated_at`、`timezone`、`scope`、`filters`、`definition` 和 `data_fresh_through`。本端点只统计当前阶段快照，不提供或暗示历史转化率。

## Phase 4 页面工作流

组织工作日日历和 Excel 导入当前只提供同源服务端页面，不承诺公共 JSON API。导入路径为 `/customer-projects/imports`，仅组织管理员/业务经理可访问；模板下载、预览、确认与撤销都执行服务端会话、CSRF、组织和角色校验。原始工作簿不进入数据库或对象存储，批次记录只保存安全文件名、SHA-256、字段映射、规范化行、错误和创建对象引用。

项目列表的 `GET /customer-projects/projects/export.xlsx` 同样是登录态页面下载，不是公共 API。它复用当前 `q` 与 `stage` 筛选和项目数据范围；组织导出策略不授权时返回 403，结果超过策略上限时重定向回列表并写入拒绝审计。成功响应不包含联系人电话或邮箱，审计记录文件 SHA-256，且响应禁止缓存。

保存视图使用同源页面端点：`POST /customer-projects/views` 创建，`POST /customer-projects/views/{id}/delete` 删除，`GET /customer-projects/projects?view={id}` 应用。视图仅保存白名单字段 `q` 和 `stage`；个人视图只对创建用户开放，组织视图只对同组织成员开放，且只有 `organization_admin` 可发布或删除组织视图。不存在匿名或跨组织共享链接。
