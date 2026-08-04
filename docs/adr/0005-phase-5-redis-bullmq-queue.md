# ADR-0005：使用 PostgreSQL Outbox + Redis/BullMQ 实现可靠异步生成

状态：Accepted  
阶段：Phase 5

## Why

图像生成耗时长、可能限流或暂时失败，不能占用前端 HTTP 生命周期。选择 PostgreSQL 保存业务事实，使用 transactional outbox 可靠发布，BullMQ/Redis 负责调度、并发、指数退避和 stalled 恢复。队列只传 job/request 标识，worker 从数据库取得敏感生成参数，使 Provider 和前端契约保持不变。

## Alternatives Considered

- API 直接 `queue.add()` 再写数据库：实现简单，但任一写入失败都会产生丢任务或幽灵任务。
- PostgreSQL `SKIP LOCKED` 自建队列：减少 Redis 组件，但延迟任务、锁续期、重试、指标和生态都需自行实现。
- RabbitMQ：路由和确认能力强，但当前只有一个生成任务类型，运维复杂度高于收益。
- Kafka：吞吐和事件回放优秀，但不适合早期任务队列的 per-job retry/cancel，成本过高。
- Redis Streams 手写 consumer group：组件少，但仍需自己实现 stalled、退避、保留和运维工具。
- exactly-once：跨 PostgreSQL、Provider 和 COS 无法经济地实现；采用 at-least-once + 业务幂等收敛。
- Redis 中保存完整 prompt：worker 读取方便，但队列数据为明文且扩大泄露面，因此拒绝。
- CVM 自建生产 Redis：成本低，但与 API/worker 同机形成单点；生产默认推荐腾讯云托管高可用实例。

## Future Impact

Phase 6 Gallery 只读取 PostgreSQL/COS，不依赖 Redis 留存。Phase 8 后台可基于观测快照展示队列，但暂停、重试等管理操作必须经过授权服务。Phase 9 多 Provider 继续复用同一 worker processor；Provider 级限流可加入独立 queue 或 BullMQ limiter。支付阶段可在 job 事务中预留积分，再由 completed/failed 状态结算。

## Performance

API 从长连接生成变为一次数据库事务，响应显著变快；新增 outbox 扫描和 Redis 往返通常远小于 GPU 推理耗时。单 worker concurrency 可配置并横向扩展。确定性 COS key 和数据库 claim 增加少量校验，却避免重复推理结果和对象膨胀。AOF/高可用会增加 Redis 写延迟，应通过实际吞吐压测调整。

## Cost

新增托管 Redis 实例及少量 CVM worker 资源；保留策略限制 Redis 内存，长期状态仍在 PostgreSQL，图片仍在 COS。托管 Redis 比同机自建成本高，但减少单点、备份、升级和恢复的人力风险。GPU/Provider 仍是主要成本，队列的并发控制和退避可减少过载与无效重试。

## Security

Redis payload 严格限定为 schema version、job id、request id、时间；额外字段直接拒绝。Redis URL、密码、prompt、Provider endpoint、凭证和 workflow 不记录日志。生产使用 VPC、安全组、ACL/密码及必要时 TLS；Redis 不对 Vercel/公网开放。取消 channel 使用严格消息 schema，worker/producer 连接角色分离，错误只保留安全码。

## Rollback Plan

先停止 dispatcher，让未发布事件安全留在 PostgreSQL；优雅关闭 worker并回滚镜像。不要清空 Redis。已 active 的任务由 stalled/重试机制或人工核对数据库状态恢复。若 Redis 故障持续，可通过 feature flag 暂停新任务消费，API 仍写 pending job/outbox；恢复后 dispatcher 继续发布。COS 对象和完成记录不回滚删除。

