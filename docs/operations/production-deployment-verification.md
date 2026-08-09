# 生产部署与真实验证 Runbook

## 当前结论

Generation API、Outbox Dispatcher、BullMQ Worker 和积分 reserve/settle/release 已
接入真实链路；Gallery 生图与视频（Ark 异步视频 + 本机 ComfyUI）已打通并完成本地
端到端验证。M4 视频迁移默认 fail-closed，生产启用前仍需 Staging 真凭据、成本、
内容安全与容量验收，并完成下方 Go/No-Go 清单。

## Go/No-Go 阻断项

- [x] Generation API、Dispatcher、Worker 有可运行入口和进程守护配置。
- [x] 前端创建、查询、取消生成任务已接入真实 API。
- [x] 提交任务在数据库事务内预占积分并写入 outbox。
- [x] 成功只结算一次；失败或取消只释放一次。
- [x] `/admin` 仅属于统一管理后台；不得长期保留两个后台。
- [x] Nginx/Caddy 已覆盖 Flask、Next、Gallery 和 Billing Webhook 路由。
- [x] staging 与 production 的数据库、Redis、COS 和支付密钥完全隔离。
- [x] 备份已在隔离数据库真实恢复。
- [ ] 视频 Provider/模型/工作流在 Staging 完成真凭据生成、成本与内容安全验收。
- [ ] 视频迁移 0013/0014 已在生产备份恢复库 dry-run，发布前备份可恢复。
- [ ] 统一后台确认视频积分价格与上游账单一致后再启用。

## 推荐启动顺序

1. PostgreSQL、Redis、COS、ComfyUI 连通性。
2. Generation Worker、Outbox Dispatcher、Generation API。
3. Gallery API、对象删除 Worker、Billing Webhook。
4. Flask、Next.js。
5. 内网健康检查通过后再加载 Nginx 公网路由。

## 发布前验证

```bash
cd services/generation-service
npm ci
npm run typecheck
npm test

cd ../../apps/gallery-web
npm ci
npm run lint
npm test
npm run build
```

数据库迁移必须按 `0001` 至 `0014` 顺序执行，已有数据库须通过 migration ledger
判断，不得盲目重跑。应用、数据库和对象存储均须保留可核验的备份或版本。

## 真实链路验证

1. 未登录、普通用户、管理员分别验证权限边界。
2. Stripe Test Mode 验证订阅、积分包、续费失败、取消、退款、重复事件和乱序事件。
3. 提交生成任务后核对 reservation、outbox、BullMQ、Provider attempt、COS object、image record 和 ledger。
4. 模拟 ComfyUI 超时、COS 上传失败、Worker 重启、Redis 中断和重复 Job。
5. 核对账户余额等于不可变账本汇总，且无长期 `reserved` 记录。
6. 使用独立恢复库验证 PostgreSQL 备份，并随机抽查 COS Object Key。
7. 视频任务验证 `pending → running → completed`、COS `videos/...` 对象、
   `ai.generation_assets` 记录、任务中心视频链接与积分结算；运行中任务不再显示取消。
8. 审核日志不含 API Key、Authorization、临时完整响应或完整 Prompt；
   临时视频 URL 不得作为业务资产返回给浏览器。

## 灰度顺序

```text
内部账号 → 1% → 10% → 50% → 100%
```

每一阶段观察 Webhook、生成成功率、失败队列、积分差异、Provider 成本、COS 错误率、数据库连接池和 Redis 内存。任一账本差异都立即停止扩量。

## 回滚

1. 隐藏付费套餐并停止创建新 Checkout。
2. 保持 Webhook 接收已支付事件，不能直接丢弃。
3. 暂停新任务投递，等待 Worker 排空或安全取消。
4. 回滚应用镜像；数据库优先前向修复，不删除支付事件或积分账本。
5. 对受影响订单人工对账，必要时退款并写入冲正账本。
6. M4 回滚时先在统一后台禁用视频 workflow/model/provider，等待运行任务终态后再回滚镜像；保留 `media_type`、`generation_assets`、账本与 COS 对象作为审计事实。

更细的单 Phase 环境变量、迁移和回滚命令见 [部署文档](../deployment/README.md)。
