# M1 Generation 生产闭环

## 已交付

- `/create` 创作工作台与 Vercel 同源 BFF。
- 工作流列表、任务创建、查询和协作取消 API。
- PostgreSQL 幂等创建、积分预留/结算/释放、Outbox 与审计。
- 可运行的 Dispatcher 与 BullMQ Worker。
- Provider attempt、COS 资产与 Gallery 图片持久化。
- 四个稳定 workflow；Provider 默认 disabled，Mock 强制非生产。
- OpenAPI、架构、ADR、Preview 部署与回滚文档。

## 验证

- Generation Service typecheck 与 57 项测试通过。
- Gallery Web ESLint 与 Next.js 生产构建通过。

## 待 Staging 验证

需要真实 PostgreSQL、Redis、COS、共享 Flask Session 和 Provider 才能完成数据库/对象存储/Vercel Preview 端到端验收。Preview 清单与发布批准完成前，生产发布为 No-Go。
