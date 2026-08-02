# Phase 8 变更记录

## 交付

- 新增管理 Dashboard、内容审核、Provider 与 Workflow 控制面。
- 新增 RBAC、审计日志和乐观并发保护。
- 输出部署文档和 ADR-0008。

## 验证

自动化、真实 PostgreSQL、BFF 和浏览器验证通过。

## 已知限制

与既有 Flask `/admin` 存在路由归属冲突，生产发布前必须合并为唯一管理后台。
