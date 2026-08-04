# Phase 10 配置、部署与回滚手册

## 默认安全状态

迁移只发布一个免费方案。所有付费方案必须由运营以真实币种、金额和 Provider Price ID 创建；Stripe 默认不注册：

```env
BILLING_STRIPE_ENABLED=false
BILLING_PUBLIC_BASE_URL=https://mindfulpenpal.com
BILLING_WEBHOOK_HOST=127.0.0.1
BILLING_WEBHOOK_PORT=8091
```

只有确认商户主体受 Stripe 支持并在 Test Mode 完成全链路验证后，才通过 Secret Manager 注入：

```env
BILLING_STRIPE_ENABLED=true
STRIPE_SECRET_KEY=<secret-manager-injected>
STRIPE_WEBHOOK_SECRET=<secret-manager-injected>
```

密钥不得写入 `.env.example`、数据库、日志、前端变量或容器镜像。`BILLING_PUBLIC_BASE_URL` 在线上必须是 HTTPS。

## 发布真实方案

先在支付渠道创建 Product/Price，再用受控管理脚本或 SQL 写入内部目录。以下只是字段模板，不是建议价格：

```sql
INSERT INTO ai.billing_plans (
  slug, display_name, description, kind, billing_interval,
  currency, amount_minor, credit_amount, entitlements,
  payment_provider, external_price_ref, is_enabled, is_public, sort_order
) VALUES (
  :slug, :display_name, :description, 'subscription', 'month',
  :currency, :amount_minor, :credit_amount, :entitlements,
  :payment_provider, :external_price_ref, false, false, :sort_order
);
```

先保持 `is_enabled=false, is_public=false`，完成 Price、税务、发票、退款条款与额度核对后再发布。升级/降级由 Provider Portal 完成，不允许用户通过 Checkout 创建第二个活跃订阅。

## 部署顺序

1. 备份 PostgreSQL，并在同版本临时实例执行 0001→0005 dry run。
2. 执行 `0005_billing_credits_memberships.sql`；验证免费方案存在且无付费方案被意外启用。
3. 部署包含 Billing API 的 Generation/Gallery Service，保持 `BILLING_STRIPE_ENABLED=false`。
4. 部署 Gallery Web；验证 `/pricing`、`/billing`、同源写请求与访客权限。
5. 配置独立 Webhook 服务：`npm run billing:webhook`。只通过反向代理暴露 `/v1/billing/webhooks/stripe`，不要暴露内部健康/管理端口。
6. 在 Stripe Test Mode 配置 Webhook Secret，订阅 Checkout、Invoice、Subscription 与 Refund 事件。
7. 创建不可公开的测试方案，以测试时钟/测试卡验证：重复投递、乱序、付款失败、取消、全额与部分退款。
8. 对账通过后配置真实方案，先内部账号灰度，再小流量公开。

## 监控与告警

- Webhook 验签失败率、重复率、处理延迟、连续失败与最老待处理年龄。
- 订单 `checkout_open` 超时、已支付但无积分流水、活跃订阅但无最近 `invoice.paid`。
- `credit_accounts` 与 ledger 聚合差异必须为零；任何差异立即冻结积分写入。
- 负余额、长期 active reservation、Provider 对账金额差异与退款冲正失败。
- 日志只记录内部 order/event ID、事件类别和安全错误码。

## 日常对账

每天从 Provider 拉取结算/退款报表，与 `payment_orders`、`subscriptions` 和 ledger source reference 对账。自动修复只能通过新的幂等流水，不允许 UPDATE/DELETE 历史流水。人工调整必须使用独立的 `admin_adjustment` 入口、双人审批和审计原因。

## 回滚

1. 先将所有付费方案设为 `is_public=false`，阻止新 Checkout。
2. 再设 `BILLING_STRIPE_ENABLED=false`，保留 Webhook 入口直到已创建订单和重试事件完全排空。
3. 回滚 Web 与 Billing API 镜像；Generation 和 Gallery 读取不依赖付费表，可继续运行。
4. 不删除订单、订阅、Webhook 收件箱、余额或 ledger。旧代码忽略新增表，可向后兼容。
5. 如果新积分预占影响生成，临时关闭新生成入口，而不是绕过余额检查；完成余额/预占对账后再恢复。
6. Schema 撤销只能使用新的 forward migration；不可编辑或反向执行 0005。先导出审计数据并确认法务保留期。

