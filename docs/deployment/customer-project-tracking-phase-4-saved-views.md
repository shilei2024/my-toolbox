# 客户项目 Phase 4 保存与组织共享视图发布手册

## 生产影响

迁移 `f7a8b9c0d1e2` 仅新增 `project_saved_views`，不修改现有项目。发布前备份 PostgreSQL，并在 staging 从 `e6f7a8b9c0d1` 完成升级、回退、再升级演练。生产升级后保持 `CUSTOMER_PROJECTS_ENABLED=false`。

## 验证步骤

1. 销售账号保存包含关键字和阶段的个人视图，刷新及重新登录后仍可使用。
2. 另一账号直接访问该视图 ID 应返回 404。
3. 组织管理员发布组织视图；同组织销售/PM/FAE/只读成员可应用，但不能删除。
4. 其他组织成员不得读取；不存在匿名分享 URL。
5. 无效阶段、空名称、同命名空间重复名称应被拒绝且不写入视图。
6. 审计包含 `project_saved_view/created` 和 `deleted`，但不包含 SQL、联系人或凭据。

## 回滚

先关闭 `CUSTOMER_PROJECTS_ENABLED`，再回退应用镜像。保留视图表和审计；旧应用不会读取它们。事故处理中不要执行 `flask db downgrade`。
