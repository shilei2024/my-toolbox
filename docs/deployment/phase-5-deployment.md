# Phase 5 部署手册

## 推荐生产形态

默认选择腾讯云分布式缓存数据库（兼容 Redis）标准高可用实例，与 CVM、PostgreSQL、COS 位于同地域/VPC。初期无需 Cluster：BullMQ key/脚本约束更简单，0.25–1 GB 起步并基于队列长度、失败保留量和内存告警扩容。高可用要求提升后再选择多可用区。

不要在现有 4 CPU / 4 GB CVM 上同时自建生产 Redis、API 与 worker：单机故障会同时丢失协调层和队列可用性。仓库中的 [compose.phase5.local.yaml](../../services/generation-service/deploy/compose.phase5.local.yaml) 仅用于本地/预发布测试。

## 服务角色

同一 Generation Service 镜像运行三个独立进程角色：

- `api`：写 PostgreSQL job + outbox，查询数据库状态，发布取消请求。
- `dispatcher`：持续领取 outbox 小批次并写 BullMQ。
- `worker`：消费任务并执行 Provider→COS 管线。

API 与 worker 使用不同 Redis connection：API 设置有限重试并关闭 offline queue，以便 Redis 不可用时快速返回 503；worker 的 `maxRetriesPerRequest=null`，等待连接恢复。

## Redis 要求

- 独立实例和 key prefix，`maxmemory-policy=noeviction`。
- 开启持久化/自动备份；自建环境使用 AOF `everysec`。
- VPC 私网、安全组最小范围、强密码/ACL；跨不可信网络使用 TLS。
- 禁止前端或 Vercel 直接访问 Redis。
- 设置内存、连接数、网络、主从切换和备份告警。

## 发布顺序

1. 创建 Redis 实例，确认版本、私网连通性、`noeviction`、备份与告警。
2. 注入 Phase 4 + Phase 5 环境变量，运行配置校验。
3. 先启动 worker，确认 `workers > 0` 和健康快照。
4. 启动 dispatcher，再部署 API；用测试 job 验证 outbox→waiting→active→COS→completed。
5. 验证 retry、waiting/active cancel、worker SIGTERM、Redis 短暂断连和 stalled 恢复。

## 容量起点

- Worker concurrency 从 1–2 开始，真正限制通常是 ComfyUI GPU 和显存，而不是 CVM CPU。
- 成功任务保留 1000、失败任务保留 5000/7 天；长期审计只在 PostgreSQL。
- waiting 持续增长时先确认 Provider/GPU 吞吐，再横向增加 worker；不要盲目提高单 worker 并发。

## 回滚

暂停 dispatcher，使新 outbox event 留在 PostgreSQL；等待或优雅关闭 worker，然后回滚镜像。API 继续接收 generation 并保存 pending/outbox，不会丢任务。恢复旧同步路径必须通过 feature flag 且仍写数据库事实状态。Redis 不执行 `FLUSHDB` 或 queue obliterate；历史 COS 和 PostgreSQL 记录保持不变。

## 验证命令

```powershell
cd services/generation-service
npm.cmd run typecheck
npm.cmd test
npm.cmd audit --omit=dev
```

当前环境 Docker daemon 未运行，因此本阶段完成了 mocked Redis/BullMQ 故障语义测试；部署环境仍必须执行真实 Redis smoke test 后再切生产流量。

