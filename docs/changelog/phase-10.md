# Phase 10 变更记录

## 交付

- 新增 Payment Provider 抽象、Stripe Adapter、订单、订阅、Webhook inbox 和客户门户。
- 新增不可变积分账本及 reserve/settle/release 数据库能力。
- 新增 Pricing、Billing 页面和 Next BFF。
- 输出配置部署文档和 ADR-0010。

## 验证

Generation Service 类型检查、53 项测试、PostgreSQL 18 migration/集成测试、Web lint、SEO、生产构建和桌面/移动浏览器验证通过。

## 已知限制

Stripe 默认关闭；国内支付尚未接入；积分能力尚未与生产生成入口形成完整事务闭环。
