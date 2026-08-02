# Architecture Decision Records

每个 Phase 完成前必须新增一份不可变 ADR。后续变化通过新 ADR 覆盖旧决策，不重写历史。

必填章节：Why、Alternatives Considered、Future Impact、Performance、Cost、Security、Rollback Plan。

## 索引

| ADR | 决策 |
| --- | --- |
| [0001](0001-phase-1-generation-service-boundary.md) | Generation Service 边界 |
| [0002](0002-phase-2-postgresql-ai-schema-and-cos.md) | PostgreSQL AI Schema 与腾讯云 COS |
| [0003](0003-phase-3-provider-contract.md) | Provider Contract |
| [0004](0004-phase-4-comfyui-cos-production-provider.md) | ComfyUI 与 COS 生产 Provider |
| [0005](0005-phase-5-redis-bullmq-queue.md) | PostgreSQL Outbox 与 BullMQ |
| [0006](0006-phase-6-gallery-service-and-next-bff.md) | Gallery Service 与 Next BFF |
| [0007](0007-phase-7-public-image-seo.md) | 公开图片 SEO |
| [0008](0008-phase-8-admin-control-plane.md) | 统一管理控制面 |
| [0009](0009-phase-9-multi-provider-routing.md) | 多 Provider 路由 |
| [0010](0010-phase-10-provider-agnostic-billing-and-credit-ledger.md) | Provider 无关支付与积分账本 |
| [0011](0011-centralized-documentation-information-architecture.md) | 统一文档信息架构 |
| [0012](0012-permanent-engineering-governance.md) | 永久工程治理与 Golden Rule |
| [0013](0013-gitflow-preview-and-immutable-release-promotion.md) | GitFlow、Preview 与不可变发布晋级 |
