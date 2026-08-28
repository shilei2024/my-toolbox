# Architecture Decision Records

每个 Phase 完成前必须新增一份不可变 ADR。后续变化通过新 ADR 覆盖旧决策，不重写历史。

必填章节：Why、Alternatives Considered、Future Impact、Performance、Cost、Security、Rollback Plan。

## 索引

| ADR | 决策 |
| --- | --- |
| [0032](0032-customer-project-material-opportunity-and-market-scope.md) | 客户项目物料机会分类与 TAM/SAM/SOM 派生 |
| [0033](0033-customer-project-comments-and-input-precision.md) | 客户项目留言/@ 与数量价格输入边界 |
| [0034](0034-material-opportunity-design-win-and-lost.md) | 物料机会四类分类与 Lost 竞品口径 |
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
| [0014](0014-generation-api-and-vercel-creation-workbench.md) | Generation API、异步生产闭环与 Vercel 创作工作台 |
| [0015](0015-m1-first-run-credits-and-operational-bindings.md) | M1 首次积分、远端 Provider 绑定与发布策略 |
| [0016](0016-phase-a-web-and-bff-security-boundaries.md) | Phase A Web 与 BFF 安全边界 |
| [0017](0017-phase-b-generation-reliability.md) | Phase B Generation Reliability and Provider Control Plane |
| [0018](0018-phase-c-performance-and-resource-bounds.md) | Phase C Performance and Resource Bounds |
| [0019](0019-phase-d-code-quality-and-governance.md) | Phase D Code Quality and Governance Cleanup |
| [0020](0020-m3-task-center-adapter-contract.md) | M3 Task Center Adapter Contract |
| [0021](0021-m5-unified-queue-observability.md) | M5 Unified Queue Observability |
| [0022](0022-gallery-mainland-access-via-tencent-self-hosting.md) | Gallery mainland access via Tencent self-hosting（已被 0023 撤销） |
| [0023](0023-gallery-deployment-stays-on-vercel.md) | Gallery 仅部署 Vercel，撤销腾讯云自托管 |
| [0024](0024-creation-workflow-api-separation-public-defaults.md) | 生图创作目录「工作流 / API」分离与公开默认值 |
| [0025](0025-gallery-media-generation-and-ark-video.md) | Gallery 复用 Generation 闭环扩展图片与视频 |
| [0026](0026-local-comfyui-media-provider-boundary.md) | 本机 ComfyUI 通过 Generation Worker 接入 Gallery |
| [0027](0027-customer-project-tracking-modular-monolith.md) | 客户项目跟进采用主站模块化单体与 PostgreSQL 事实源 |
| [0028](0028-customer-project-lifecycle-reuse-and-derivation.md) | 客户项目重新激活、衍生与快照报表边界 |
| [0029](0029-customer-project-calendar-and-controlled-import.md) | 共享工作日日历与受控 Excel 导入边界 |
| [0030](0030-customer-project-controlled-export.md) | 客户项目受控导出策略与文件安全边界 |
| [0031](0031-customer-project-saved-views.md) | 客户项目个人与组织筛选视图边界 |
