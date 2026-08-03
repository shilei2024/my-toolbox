# MindfulPenPal AI Toolbox Platform 路线图

## 平台定位

MindfulPenPal 不再按单一 AI 图片生成器演进，而是面向未来五年的 AI 工具平台。图片是第一个模块，后续可扩展视频、OCR、PDF、写作、Chat、音频和翻译。

## 不可违反的原则

所有里程碑首先执行[永久工程原则与 Golden Rule](../architecture/engineering-principles.md)。

1. 只建设一个统一管理后台，用户、积分、订单、内容、Provider、模型、任务、配置、日志与监控统一管理。
2. 支付业务依赖统一 Payment Provider 契约；中国用户优先微信支付和支付宝，Stripe 作为国际回退。
3. AI 业务只能调用内部 Generation/Task Service，不能在前端或模块代码中绑定供应商。
4. 腾讯云 COS 是当前默认永久存储；ComfyUI 输出只作临时文件，Storage Provider 必须可替换。
5. PostgreSQL 是业务事实来源；Redis/BullMQ 只承担调度和短期运行状态。
6. 认证、积分、支付、Provider Registry、存储、队列、任务历史、通知、日志、监控和配置均建设为共享能力。
7. 每个里程碑必须包含 ADR、时序图、部署、配置、故障排查、回滚、成本、安全和未来扩展说明。

## 已完成基础阶段

| 阶段 | 能力 | 状态 |
| --- | --- | --- |
| Phase 1–3 | 服务边界、PostgreSQL/COS 数据设计、Provider 契约 | 已完成 |
| Phase 4–5 | ComfyUI Adapter、可靠异步队列核心 | 已完成核心实现 |
| Phase 6–8 | Gallery、SEO、管理控制面 | 已完成模块实现 |
| Phase 9–10 | 多 Provider、支付/积分/会员抽象 | 已完成核心实现，真实商户与生成扣费接线待完成 |

## 后续里程碑

| 里程碑 | 交付内容 | 依赖 | 风险 |
| --- | --- | --- | --- |
| M1 生产闭环 | Generation API、Dispatcher/Worker 入口、积分原子预占/结算、统一 Admin 路由 | Phase 1–10 | 代码完成；待 Staging 基础设施与 Vercel Preview 验收 |
| M2 国内支付 | Payment Provider 契约固化、微信支付、支付宝、退款与对账 | M1 | 商户资质、回调幂等、财务合规 |
| M3 平台任务中心 | 通用 Task Schema、跨模块历史、通知、成本与 SLA | M1 | 过度抽象、迁移复杂度 |
| M4 AI 视频/OCR | 复用任务、积分、存储、Provider Registry 接入两个新模块 | M3 | 大文件、长任务、成本失控 |
| M5 可观测与增长 | 统一指标、告警、配额、优惠券、反馈、SEO 增长 | M2–M4 | 指标隐私、促销滥用 |

## 部署顺序

```text
共享数据库与审计
→ 存储 Provider
→ Redis/BullMQ
→ Provider Registry
→ Task/Generation API + Worker
→ Credits/Billing
→ 统一 Admin
→ Gallery/SEO
→ 新 AI 模块
```

## 生产就绪门禁

- 任务、支付、积分和对象存储具备幂等与审计。
- 数据库备份已真实恢复，Provider 与 Redis 故障已演练。
- 前端不知道 AI、支付和存储供应商密钥及内部路由。
- 管理后台唯一，所有高风险操作具备 RBAC、审计和乐观并发。
- 部署教程可由无 DevOps 经验的操作者按预期输出逐步验证。
- 成本按用户、模块、Provider、模型和任务可追踪。
