# Phase 5 变更记录

## 交付

- 新增 PostgreSQL Outbox、Redis/BullMQ 队列、重试、取消和 Worker 核心。
- Redis 只保存调度标识，业务参数和审计继续保存在 PostgreSQL。
- 输出配置、部署和 ADR-0005。

## 验证

类型、队列契约和故障语义测试通过。

## 已知限制

生产 Generation API、Dispatcher、Worker main entrypoint 仍需完成运行时装配。
