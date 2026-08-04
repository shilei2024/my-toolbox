# ADR 0014：Generation API 与 Vercel 创作工作台

## Why

Phase 1–10 已有 Provider、队列、Gallery 和积分核心，但网站缺少创建/查询/取消生产契约，AI 生图无法作为共享用户体系中的真实工具使用。

## Decision

在现有 Gallery Fastify 进程加入内部 Generation API；Next.js 在 Vercel 仅提供同源 BFF 和 `/create` 页面。创建事务原子写入 job、积分预留、Outbox 和审计；Dispatcher 与 Worker 独立进程运行。

## Alternatives Considered

- Vercel 函数直接调用 Provider：拒绝，超时、密钥、重试和计费边界错误。
- Flask 恢复旧生图模块：拒绝，会重新引入内存任务和本地文件。
- 新建另一套用户或后台：拒绝，破坏统一认证与管理控制面。

## Future Impact

未来模块可复用任务创建、幂等、积分、Outbox、状态查询和取消语义；模块差异保留在 workflow schema 与 Provider Adapter。

## Performance

创建接口只执行短数据库事务并返回 202。前端两秒轮询，后续可无契约破坏地升级 SSE。Outbox 小批量领取，Worker 并发由环境变量控制。

## Cost

不增加新供应商；复用 PostgreSQL、Redis、COS 和现有 Vercel 项目。Mock 只用于 Staging，生产必须使用已批准 Provider。

## Security

浏览器只访问同源 BFF；HMAC 身份、Origin、RBAC、输入上限、幂等和脱敏错误均由服务端强制。Provider/COS 密钥不进入前端。

## Rollback Plan

隐藏 AI 工具入口，停止 Dispatcher/Worker，回滚 Vercel Preview 和后端镜像。保留数据库事实和对象；将 Provider/Workflow 设为 disabled，不删除已引用记录。
