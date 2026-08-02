# Phase 6 变更记录

## 交付

- 新增 Gallery Service、Next.js SSR/BFF、公开/私有查询、收藏、点赞和延迟对象删除。
- 新增 Gallery 数据库 migration、缓存与内部签名 Viewer Context。
- 输出配置、部署和 ADR-0006。

## 验证

自动化测试和真实 PostgreSQL 集成测试通过。

## 已知限制

公网只应暴露 Next BFF，内部 `/v1/*` 不得直接开放。
