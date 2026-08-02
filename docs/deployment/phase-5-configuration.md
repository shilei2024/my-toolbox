# Phase 5 配置手册

队列配置由 `loadGenerationQueueConfig()` 启动时严格读取。没有隐含生产默认值；错误 URL、非法名称或非正整数会阻止服务启动。

| 环境变量 | 说明 | 推荐初始值 |
| --- | --- | --- |
| `REDIS_URL` | Redis/Valkey URL；生产凭证通过密钥系统注入 | `rediss://...` 或 VPC `redis://...` |
| `BULLMQ_PREFIX` | Redis key namespace | `ai-image-prod` |
| `BULLMQ_QUEUE_NAME` | generation queue 名 | `image-generation` |
| `BULLMQ_CANCEL_CHANNEL` | 跨进程取消 channel | `generation-cancel` |
| `BULLMQ_CONCURRENCY` | 单 worker 并发 | `2`，再按 GPU/Provider 限额压测 |
| `BULLMQ_ATTEMPTS` | 包含首次执行的总次数 | `3` |
| `BULLMQ_BACKOFF_MS` | exponential backoff 基数 | `1000` |
| `BULLMQ_COMPLETED_RETENTION_COUNT` | Redis 保留成功任务数 | `1000` |
| `BULLMQ_FAILED_RETENTION_COUNT` | Redis 保留失败任务数 | `5000` |
| `BULLMQ_RETENTION_AGE_SECONDS` | 最长保留时间 | `604800`（7 天） |
| `BULLMQ_MAX_STALLED_COUNT` | stalled 恢复上限 | `1` |
| `BULLMQ_LOCK_DURATION_MS` | worker lock 时长 | `30000` |
| `BULLMQ_GRACEFUL_SHUTDOWN_MS` | 优雅停机等待 | `30000` |
| `GENERATION_OUTBOX_BATCH_SIZE` | Dispatcher 单批事件数 | `100` |
| `GENERATION_OUTBOX_RETRY_BASE_MS` | outbox 重试基数 | `1000` |
| `GENERATION_OUTBOX_RETRY_MAX_MS` | outbox 最大延迟 | `60000` |

示例：

```dotenv
REDIS_URL=redis://:replace-at-deploy-time@redis.internal:6379/0
BULLMQ_PREFIX=ai-image-prod
BULLMQ_QUEUE_NAME=image-generation
BULLMQ_CANCEL_CHANNEL=generation-cancel
BULLMQ_CONCURRENCY=2
BULLMQ_ATTEMPTS=3
BULLMQ_BACKOFF_MS=1000
BULLMQ_COMPLETED_RETENTION_COUNT=1000
BULLMQ_FAILED_RETENTION_COUNT=5000
BULLMQ_RETENTION_AGE_SECONDS=604800
BULLMQ_MAX_STALLED_COUNT=1
BULLMQ_LOCK_DURATION_MS=30000
BULLMQ_GRACEFUL_SHUTDOWN_MS=30000
GENERATION_OUTBOX_BATCH_SIZE=100
GENERATION_OUTBOX_RETRY_BASE_MS=1000
GENERATION_OUTBOX_RETRY_MAX_MS=60000
```

真实 URL 不得写入仓库、日志或前端。Redis 内存策略必须是 `noeviction`；开启持久化/备份，且不要与普通 cache 共用实例。

