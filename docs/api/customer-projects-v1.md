# Customer Projects API v1（Phase 1 核心契约）

> 状态：Phase 1 核心端点已实现，功能开关默认关闭，尚未部署生产。提醒、报表、重新激活和衍生端点属于后续 Phase。

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
| POST | `/projects/{project_id}/materials` | 新增物料，可同时录入单机数量和单价 | `Idempotency-Key` |
| PATCH | `/materials/{material_id}` | 更新单机数量和单价 | `If-Match`；仅业务/PM 价格角色 |
| POST | `/materials/{material_id}/competitors` | 新增竞争方案 | `Idempotency-Key` |
| POST | `/trash/projects/{project_id}/restore` | 管理员恢复软删除项目 | 组织与角色校验 |

项目更新允许修改名称、产品名称、项目年用量、评估等级、概率档位、下一步、下次跟进时间、预计定点日期和预计量产日期；仍必须通过 `If-Match` 携带当前版本。新建项目要求 `product_name` 和大于 0 的 `annual_usage`，兼容迁移前的旧项目记录可暂时返回 `null`。

客户/联系人在 Phase 1 通过服务端页面提供；其稳定 JSON CRUD，以及物料/竞品编辑与软删除、项目重新激活/衍生、报表和通知 API 在后续切片补齐。未实现端点不返回伪成功。

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
  "machine_quantity": "2",
  "unit_price": "1.25",
  "currency": "USD"
}
```

`currency` 仅支持 `USD` 或 `CNY`。USD 输入视为未税美元，服务端按主站 USD/CNY 汇率乘以 `1.13` 得到含税人民币；CNY 输入视为已含 13% 增值税，再反算未税美元。响应同时返回 `unit_price_usd`、`unit_price_cny_tax_included`、`fx_rate_usd_cny` 和原始录入币别。服务端保存折算快照，后续汇率变化不会修改历史单价。

价格写入只允许组织管理员、业务经理、`sales` 和 `pm`；FAE 可以更新 `machine_quantity`，也可以查看折算结果，但提交 `unit_price` 返回 403。汇率服务不可用且无缓存时，价格不保存并返回 422；客户端预览只用于展示，最终结果以服务端计算为准。

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

每份报表必须带 `generated_at`、`timezone`、`scope`、`filters`、`definition` 和 `data_fresh_through`。漏斗按当前阶段统计，历史转化按阶段事件统计，不共用含糊的“转化率”字段。
