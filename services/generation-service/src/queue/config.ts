export interface GenerationQueueConfig {
  readonly redisUrl: string;
  readonly prefix: string;
  readonly queueName: string;
  readonly cancellationChannel: string;
  readonly concurrency: number;
  readonly attempts: number;
  readonly backoffMs: number;
  readonly completedRetentionCount: number;
  readonly failedRetentionCount: number;
  readonly retentionAgeSeconds: number;
  readonly maxStalledCount: number;
  readonly lockDurationMs: number;
  readonly gracefulShutdownMs: number;
  readonly outboxBatchSize: number;
  readonly outboxRetryBaseMs: number;
  readonly outboxRetryMaxMs: number;
  readonly providerHealthCheckMs: number;
  readonly providerHealthFailureThreshold: number;
  readonly reconciliationIntervalMs: number;
  readonly runningJobTimeoutMs: number;
  readonly reconciliationBatchSize: number;
}

export class QueueConfigurationError extends Error {
  readonly key: string;
  constructor(key: string, message = `Missing or invalid environment variable: ${key}`) {
    super(message);
    this.name = "QueueConfigurationError";
    this.key = key;
  }
}

export function loadGenerationQueueConfig(env: NodeJS.ProcessEnv = process.env): GenerationQueueConfig {
  const redisUrl = required(env, "REDIS_URL");
  assertRedisUrl(redisUrl);
  return {
    redisUrl,
    prefix: safeName(env, "BULLMQ_PREFIX"),
    queueName: safeName(env, "BULLMQ_QUEUE_NAME"),
    cancellationChannel: safeName(env, "BULLMQ_CANCEL_CHANNEL"),
    concurrency: positiveInt(env, "BULLMQ_CONCURRENCY"),
    attempts: positiveInt(env, "BULLMQ_ATTEMPTS"),
    backoffMs: positiveInt(env, "BULLMQ_BACKOFF_MS"),
    completedRetentionCount: positiveInt(env, "BULLMQ_COMPLETED_RETENTION_COUNT"),
    failedRetentionCount: positiveInt(env, "BULLMQ_FAILED_RETENTION_COUNT"),
    retentionAgeSeconds: positiveInt(env, "BULLMQ_RETENTION_AGE_SECONDS"),
    maxStalledCount: nonNegativeInt(env, "BULLMQ_MAX_STALLED_COUNT"),
    lockDurationMs: positiveInt(env, "BULLMQ_LOCK_DURATION_MS"),
    gracefulShutdownMs: positiveInt(env, "BULLMQ_GRACEFUL_SHUTDOWN_MS"),
    outboxBatchSize: positiveInt(env, "GENERATION_OUTBOX_BATCH_SIZE"),
    outboxRetryBaseMs: positiveInt(env, "GENERATION_OUTBOX_RETRY_BASE_MS"),
    outboxRetryMaxMs: positiveInt(env, "GENERATION_OUTBOX_RETRY_MAX_MS"),
    providerHealthCheckMs: boundedInt(env, "GENERATION_PROVIDER_HEALTH_CHECK_MS", 60_000, 1_000, 3_600_000),
    providerHealthFailureThreshold: boundedInt(env, "GENERATION_PROVIDER_HEALTH_FAILURE_THRESHOLD", 3, 1, 100),
    reconciliationIntervalMs: boundedInt(env, "GENERATION_RECONCILIATION_INTERVAL_MS", 60_000, 1_000, 3_600_000),
    runningJobTimeoutMs: boundedInt(env, "GENERATION_RUNNING_JOB_TIMEOUT_MS", 900_000, 60_000, 86_400_000),
    reconciliationBatchSize: boundedInt(env, "GENERATION_RECONCILIATION_BATCH_SIZE", 50, 1, 1_000),
  };
}

function required(env: NodeJS.ProcessEnv, key: string): string {
  const value = env[key]?.trim();
  if (!value) throw new QueueConfigurationError(key);
  return value;
}

function positiveInt(env: NodeJS.ProcessEnv, key: string): number {
  const value = Number(required(env, key));
  if (!Number.isSafeInteger(value) || value <= 0) throw new QueueConfigurationError(key);
  return value;
}

function nonNegativeInt(env: NodeJS.ProcessEnv, key: string): number {
  const value = Number(required(env, key));
  if (!Number.isSafeInteger(value) || value < 0) throw new QueueConfigurationError(key);
  return value;
}

function boundedInt(env: NodeJS.ProcessEnv, key: string, fallback: number, min: number, max: number): number {
  const raw = env[key]?.trim();
  const value = raw ? Number(raw) : fallback;
  if (!Number.isSafeInteger(value) || value < min || value > max) throw new QueueConfigurationError(key, `${key} must be an integer between ${min} and ${max}`);
  return value;
}

function safeName(env: NodeJS.ProcessEnv, key: string): string {
  const value = required(env, key);
  if (!/^[a-z0-9][a-z0-9_-]{1,62}$/i.test(value)) throw new QueueConfigurationError(key, `${key} contains unsupported characters`);
  return value;
}

function assertRedisUrl(value: string): void {
  let url: URL;
  try { url = new URL(value); } catch { throw new QueueConfigurationError("REDIS_URL", "REDIS_URL must be a valid Redis URL"); }
  if (url.protocol !== "redis:" && url.protocol !== "rediss:") throw new QueueConfigurationError("REDIS_URL", "REDIS_URL must use redis:// or rediss://");
}
