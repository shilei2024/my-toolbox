# 客户项目跟进 Phase 1 运维手册

## 当前能力

Phase 1 提供核心台账，不包含自动提醒或邮件发送。生产默认 `CUSTOMER_PROJECTS_ENABLED=false`；未完成 PostgreSQL staging 和发布审批前不得开启。

## 日常检查

1. 检查 `/healthz`、登录、统一后台和现有工具无异常。
2. 功能开放后检查客户项目 API 的请求量、4xx/5xx、P95 延迟和 409 冲突数量。
3. 检查项目列表中逾期和 14 天未更新数量；Phase 1 仅展示，不自动通知。
4. 检查数据库备份包含 `organizations`、`organization_memberships`、`customers`、`customer_projects`、项目子表和 `audit_events`。

## 账号或权限异常

- 用户看不到入口：确认功能开关、试点邮箱、账号有效状态和组织成员状态。
- 用户看到入口但 403：确认至少有一个受支持角色；不得通过修改前端绕过。
- 用户不应再访问：在统一后台把成员状态改为停用。历史项目和审计保留，用户不会继续获得业务数据。
- 跨组织数据可见：立即关闭功能开关并按安全事件处理，保留请求追踪 ID，不导出真实客户信息到工单。

## 冲突与数据恢复

409 表示另一个终端先保存成功；这是数据保护，不是服务器故障。让用户复制未保存内容、刷新最新版本后人工合并。软删除项目从模块回收站恢复；不得直接修改数据库或删除阶段/活动历史。

## 回滚

先设置 `CUSTOMER_PROJECTS_ENABLED=false` 并重启/滚动更新应用，再回退到上一稳定应用包。保留 migration `8904db6a3fa5` 创建的表和所有业务记录；事故处理中禁止执行 Alembic downgrade。恢复步骤以[Phase 1 发布计划](../deployment/customer-project-tracking-phase-1-rollout.md)为准。
