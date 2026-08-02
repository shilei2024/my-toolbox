# ADR-0010：Provider 无关支付边界与不可变积分账本

状态：Accepted  
阶段：Phase 10

## Why

支付渠道、会员权益和生成额度具有不同的一致性与合规边界。渠道事件可能重复、乱序和延迟；生成任务需要低延迟原子扣减；前端又不应知道具体支付 Provider。因此决定引入内部 `PaymentProvider` Adapter、独立 Billing Service、异步 Webhook Inbox，以及 PostgreSQL 不可变积分账本。Stripe 只是首个 Adapter，默认关闭；只有商户主体与运营配置合规后才启用。支付成功不是直接改余额，而是通过带唯一幂等键的 ledger entry 更新账户投影。

## Alternatives Considered

- 前端直接集成 Stripe/微信/支付宝 SDK：接入快，但会泄漏渠道选择并把回调、会员和错误语义耦合到 UI，放弃。
- 只在 `users` 表保存一个 `credits` 数字：查询快，但无法对账、解释退款或恢复并发事故，放弃。
- 以 Provider Subscription 状态作为权限事实：省去内部投影，但乱序和渠道迁移会直接破坏访问控制，放弃。
- Webhook 验签后同步完成全部业务再返回：实现简单，但容易超时并触发重复投递，改为先持久化后异步处理。
- 保存完整 Webhook Payload：排障方便，但扩大支付 PII 与数据保留风险，改为保存最小标准化事件和原文 SHA-256。
- 使用 JavaScript number 保存积分：开发方便，但存在二进制浮点误差，改用 PostgreSQL `numeric(18,4)` 和 JSON 字符串。
- 用户积分按 Provider 实际成本事后浮动扣费：成本精确，但价格不可预期且可能透支，改为按预先确定的用户价格预占和结算，实际成本单独审计。
- 为中国大陆主体直接默认启用 Stripe：无法满足当前商户可用地区约束，放弃；保留本地支付 Adapter 入口。

## Future Impact

新增微信支付、支付宝、Gemini 订阅或其他渠道只需实现内部 Provider Contract 和事件标准化，不改前端、积分表或 Generation Service。会员权益可继续扩展为版本化 entitlement；用量计费、企业账户、发票与礼品码应继续写入同一 ledger，而不是增加旁路余额。后续需要增加定时对账、积分快照校验、过期策略、税务/发票服务、争议处理和双人审批的 Admin 调整入口。

## Performance

余额读取命中单行投影，不需要实时聚合 ledger。预占在账户行上加锁并在单事务内完成，热点大客户可能形成行级串行化，但换来不会超扣的强一致性；企业账户可未来分桶或拆分项目额度。Webhook 入口只验签、插入和返回 202，重处理由 `SKIP LOCKED` 横向扩展。最近流水使用 `(user_id, created_at DESC, id DESC)` 索引。每次额度变化多一次账户 UPDATE 和一次 ledger INSERT，属于可接受的审计成本。

## Cost

主要新增成本是支付渠道手续费、退款/争议成本、少量 PostgreSQL 存储与一个轻量 Webhook Worker。采用 Provider 托管 Checkout/Portal 可减少 PCI 范围和自建支付 UI 维护成本。默认不发布虚构付费价格，也不在未确认商户主体时产生 Stripe 固定投入。COS、生成 Provider 与支付费用分别核算，避免用一个积分字段掩盖真实毛利。

## Security

支付密钥只从 Secret Manager/环境注入，浏览器、数据库和日志不保存密钥。Webhook 在独立 raw-body 入口使用官方 SDK 验签，限制 256 KiB、速率与支持的事件类型；完整支付对象不落库。BFF 写接口执行同源检查并使用短期 HMAC 身份。Checkout/Portal URL 必须是 HTTPS，Checkout URL 完成后清空。订单、Webhook 和 ledger 都有幂等唯一约束；ledger 拒绝 UPDATE/DELETE。退款允许形成负余额以保留账务事实，同时生成预占会阻止余额不足账户继续消费。

## Rollback Plan

先隐藏所有付费方案，停止新 Checkout；保持 Webhook 入口处理已有订单，待 Inbox 排空后关闭 Provider 注册。随后可回滚 Web/Billing 镜像，新增表由旧服务忽略。绝不删除或篡改订单、订阅和 ledger；需要修复时追加相反方向的幂等流水。若额度检查异常，暂停新的生成提交并完成余额与预占对账，不允许临时绕过扣费。Schema 清理由新的 forward migration 执行，且必须满足审计/法务保留要求。
