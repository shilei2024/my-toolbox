# 客户项目跟进运维手册

## 当前能力

Phase 1 提供核心台账；Phase 2 首个切片提供提醒策略、幂等发件箱、dry-run/SMTP 发送、重试和心跳。生产默认 `CUSTOMER_PROJECTS_ENABLED=false`、`CUSTOMER_PROJECT_REMINDERS_ENABLED=false`、`CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=false`；未完成 PostgreSQL staging、dry-run 和发布审批前不得开启。

## 日常检查

1. 检查 `/healthz`、登录、统一后台和现有工具无异常。
2. 功能开放后检查客户项目 API 的请求量、4xx/5xx、P95 延迟和 409 冲突数量。
3. 检查项目列表中逾期、今日到期、7 天内到期和长期未更新数量，并在统一后台核对扫描/发送心跳、最老待发、失败和死信状态。
4. 检查数据库备份包含 `organizations`、`organization_memberships`、`customers`、`customer_projects`、项目子表、`audit_events`、提醒策略、通知发件箱、投递和心跳表。
5. 抽查 Excel 导出审计中的项目数、物料数和筛选标记；导出文件可能含客户与价格信息，只能通过受控业务账号下载和传递。

## 汇率与价格异常

- 页面汇率预览失败但无保存动作：刷新后重试；预览不是最终计算依据。
- 保存单价提示汇率不可用：不要手工猜测汇率或直接改库。确认服务器可访问主站汇率上游；若已有缓存，系统会标记为过期缓存并继续使用，完全无缓存时整笔价格写入不会落库。
- 折算结果争议：核对物料记录中的原始录入币别、`fx_rate_usd_cny` 和更新时间。USD 按未税口径，CNY 按含 13% 增值税口径。
- FAE 无法编辑单价属于预期权限；如需授权，应由统一后台调整为业务或 PM 角色并保留审批记录，不得改前端绕过。

## 账号或权限异常

- 用户看不到入口：确认功能开关、试点邮箱、账号有效状态和组织成员状态。
- 用户看到入口但 403：确认至少有一个受支持角色；不得通过修改前端绕过。
- 用户不应再访问：在统一后台把成员状态改为停用。历史项目和审计保留，用户不会继续获得业务数据。
- 跨组织数据可见：立即关闭功能开关并按安全事件处理，保留请求追踪 ID，不导出真实客户信息到工单。

## 冲突与数据恢复

409 表示另一个终端先保存成功；这是数据保护，不是服务器故障。让用户复制未保存内容、刷新最新版本后人工合并。软删除项目从模块回收站恢复；不得直接修改数据库或删除阶段/活动历史。

## 回滚

先关闭提醒扫描和真实发送，再设置 `CUSTOMER_PROJECTS_ENABLED=false` 并重启/滚动更新应用。保留 migrations `8904db6a3fa5`、`f1a2b3c4d5e6`、`a2b3c4d5e6f7` 与 `b3c4d5e6f7a8` 创建的表、列和业务记录；事故处理中禁止执行 Alembic downgrade。基础台账恢复见[Phase 1 发布计划](../deployment/customer-project-tracking-phase-1-rollout.md)，提醒见[Phase 2 部署与回滚](../deployment/customer-project-tracking-phase-2-reminders.md)。
