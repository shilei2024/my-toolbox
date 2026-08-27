# 客户项目跟进系统 Phase 1 架构

## 实施状态

Phase 1 核心台账已在 Flask 主站中实现，功能开关默认关闭。当前代码包含组织和成员角色、客户/联系人、项目、项目成员、推广物料、竞争方案、追加式跟进、阶段历史、脱敏审计、软删除/恢复、服务端权限、乐观锁、响应式页面及 JSON API。项目详情页支持基础信息编辑，工作台提醒按组织本地日界线互斥计算，详情时间线统一合并跟进和阶段事件并按最新时间排序。Phase 2 的提醒扫描、通知发件箱和 SMTP 适配器尚未实现，不得将本文理解为提醒闭环已经上线。

## 目标与边界

本模块把电子元器件代理业务中的客户项目变成唯一、可追溯的业务事实，覆盖客户、成员、推广物料、竞争方案、跟进和生命周期。V1 不承担 ERP、库存、报价、订单、合同、群发营销或原生移动客户端职责。

本文件记录 Phase 1 已实现边界；产品验收仍以[PRD](../product/customer-project-tracking-prd.md)为准，关键取舍见 [ADR 0027](../adr/0027-customer-project-tracking-modular-monolith.md)。

## 运行边界

```mermaid
flowchart TD
  B["桌面/移动浏览器"] --> F["Flask 主站"]
  F --> A["现有认证、会话与 CSRF"]
  F --> C["customer_projects 页面与 API"]
  C --> D["领域服务：权限、状态机、乐观锁"]
  D --> P[("PostgreSQL 业务事实源")]
  D --> O["共享审计与通知意图"]
  O --> P
  S["外部调度器"] --> I["签名内部入口/CLI"]
  I --> O
  O --> M["可替换 SMTP 适配器"]
  F --> U["现有统一后台"]
```

## 建议代码边界

```text
customer_projects/
  __init__.py
  routes.py                 # 服务端页面，薄控制器
  api.py                    # /api/v1/customer-projects
  forms.py                  # HTML 输入校验
  schemas.py                # JSON 边界校验和序列化
  models.py                 # 本领域模型
  permissions.py            # 组织与项目授权策略
  services/
    projects.py
    activities.py
    lifecycle.py
    reminders.py
  repositories/
    projects.py
  queries/
    dashboard.py
    reports.py
shared/
  organizations/            # 组织和成员
  audit/                    # 脱敏审计事件
  notifications/            # 意图、发件箱、适配器
templates/customer_projects/
static/customer_projects/
tests/customer_projects/
migrations/versions/
```

共享目录只接收已有第二个或明确计划中的消费者；Phase 1 可先通过稳定接口在同一提交内落地，避免为复用而过度抽象。

## 权限模型

访问判定顺序固定为：已登录且账号有效 → 功能开关/试点范围 → 有效组织成员 → 组织角色 → 项目成员/数据范围 → 对象未删除或具有回收站权限。平台管理员不会因 `is_admin` 自动获得所有业务内容；代查必须进入显式授权和审计路径。

| 能力 | 组织管理员 | 业务经理 | 项目成员 | 只读/审计 |
| --- | --- | --- | --- | --- |
| 创建客户/项目 | 是 | 是 | 是 | 否 |
| 编辑参与项目 | 是 | 是 | 是 | 否 |
| 分配成员 | 是 | 是 | 依策略 | 否 |
| 确认量产/失败 | 是 | 是 | 仅发起 | 否 |
| 恢复软删除 | 是 | 项目范围内 | 否 | 否 |
| 查看审计 | 是 | 数据范围内 | 本项目可读事件 | 否 |

## 项目状态机

正常推进允许顺序前进；跨阶段必须提供原因。任何进入量产、失败、暂停、归档、重新激活或衍生的操作必须带幂等键并写阶段事件和审计。

```mermaid
stateDiagram-v2
  [*] --> evaluation
  evaluation --> initiated
  initiated --> sampling
  sampling --> pilot_batch
  pilot_batch --> trial_production
  trial_production --> design_win
  design_win --> mass_production
  evaluation --> paused
  initiated --> paused
  sampling --> paused
  pilot_batch --> paused
  trial_production --> paused
  design_win --> paused
  paused --> evaluation: 重新激活
  paused --> initiated: 重新激活
  paused --> sampling: 重新激活
  evaluation --> lost
  initiated --> lost
  sampling --> lost
  pilot_batch --> lost
  trial_production --> lost
  design_win --> lost
  mass_production --> archived
  lost --> archived
  archived --> evaluation: 重新激活
```

条件校验：量产要求有效物料、日期和说明；失败要求原因和说明；暂停要求原因；重新激活要求目标阶段、原因、下一步和时间。阶段跳转保留前后状态、原因、操作者、审批者和发生时间。

## 一致性与并发

- 项目详情返回 `version`；PATCH 使用 `If-Match: \"<version>\"`，SQL 更新条件同时包含 `id`、`organization_id` 和旧版本。
- 影响行数为 0 时重新读取：不存在/不可见返回 404，版本变化返回 409；不得用后提交内容覆盖先提交内容。
- 新增有效跟进、更新项目快照、递增版本、写审计和取消旧提醒意图在同一事务完成。
- 网络发送永远不在业务事务中执行；发件箱以唯一幂等键防重复。
- 所有时间以带时区 UTC 写入，显示和邮件按组织时区，默认 `Asia/Shanghai`。

## 读模型与容量

工作台按“今日到期、逾期、即将到期、长期未更新、待重新分配、最近更新”提供有界查询。项目、客户、物料、竞品搜索统一先做组织和权限过滤；列表默认 25 条、最大 100 条，游标由排序值和稳定 ID 构成。报表必须返回口径、数据范围、筛选时间与生成时间。

## 可观测性

指标至少覆盖请求量、错误率、延迟、409 冲突、提醒扫描心跳、待发数量、最老待发时长、发送成功率、永久失败、逾期项目和严重停滞项目。日志只写追踪 ID、不可逆组织标识、对象稳定 ID 和安全错误码，不写邮件正文、联系人完整信息或内部异常细节。

## Phase 1 已实现切片

1. Flask-Migrate/Alembic 迁移框架、默认关闭的功能开关、试点邮箱、组织/成员与默认阶段字典。
2. 客户、联系人、项目、成员、物料、竞品、活动、阶段事件和审计模型。
3. 服务端 RBAC、状态机条件校验、事务服务、软删除/恢复、幂等键和乐观锁。
4. 工作台、项目列表/筛选、客户与联系人、新建/详情、移动端跟进、物料/竞品、成员和回收站页面；授权试点用户可从主站首页客户项目卡片进入。
5. `/api/v1/customer-projects` 的项目查询/创建/更新、跟进、阶段、物料、竞品、软删除和恢复契约。

本地隔离 SQLite 已完成页面人工验收：登录、组织初始化、客户/联系人、项目创建/编辑、跟进、物料/竞品、阶段流转、列表检索、工作台和 320/768/1280 响应式检查，浏览器控制台无错误。尚未完成的 Phase 1 发布验收：真实 PostgreSQL 集成、生产规模性能、备份恢复、staging 人工响应式检查和生产发布审批。功能开关必须保持关闭，直到这些门禁通过。

提醒发件箱的共享骨架可在 Phase 1 建表，但扫描、适配器和重试属于 Phase 2；量产/失败报表、激活和衍生属于 Phase 3。
