import { ConsoleStructuredLogger } from "../pipeline/structured-logger.ts";
import { createDatabasePool } from "../database/pool.ts";
import { loadGenerationQueueConfig } from "./config.ts";
import { createGenerationQueue, GenerationQueueService } from "./generation-queue-service.ts";
import { GenerationOutboxDispatcher } from "./outbox-dispatcher.ts";
import { PostgresGenerationOutboxRepository } from "./postgres-outbox-repository.ts";
import { createGenerationRedisConnections } from "./redis-connections.ts";

const databaseUrl = process.env.DATABASE_URL?.trim();
if (!databaseUrl) throw new Error("DATABASE_URL is required");
const pollMs = positiveInteger(process.env.GENERATION_OUTBOX_POLL_MS, 1000, "GENERATION_OUTBOX_POLL_MS");
const config = loadGenerationQueueConfig();
const logger = new ConsoleStructuredLogger();
const pool = createDatabasePool(databaseUrl, { max: 5 });
const redis = createGenerationRedisConnections(config, logger);
const queue = createGenerationQueue(redis.producer, config, logger);
const queueService = new GenerationQueueService(queue, redis.publisher, config);
const dispatcher = new GenerationOutboxDispatcher(new PostgresGenerationOutboxRepository(pool), queueService, {
  batchSize: config.outboxBatchSize, retryBaseMs: config.outboxRetryBaseMs, retryMaxMs: config.outboxRetryMaxMs,
}, logger);
let stopping = false;
let consecutiveFailures = 0;

const stop = () => { stopping = true; };
process.once("SIGINT", stop);
process.once("SIGTERM", stop);
logger.info("queue.dispatcher_started", { pollMs, batchSize: config.outboxBatchSize });
while (!stopping) {
  try {
    const result = await dispatcher.runOnce();
    consecutiveFailures = 0;
    if (result.claimed === 0) await delay(pollMs);
  } catch (error) {
    consecutiveFailures += 1;
    const backoffMs = Math.min(30_000, 1_000 * 2 ** Math.min(consecutiveFailures - 1, 5));
    logger.error("queue.dispatcher_run_failed", {
      failureReason: "database_error",
      errorMessage: String(error).slice(0, 300),
      backoffMs,
      consecutiveFailures,
    });
    await delay(backoffMs);
  }
}
await queueService.close();
await redis.producer.quit();
await pool.end();
logger.info("queue.dispatcher_stopped", {});

function positiveInteger(raw: string | undefined, fallback: number, name: string): number {
  const value = raw?.trim() ? Number(raw) : fallback;
  if (!Number.isSafeInteger(value) || value < 100 || value > 60_000) throw new Error(`${name} must be an integer between 100 and 60000`);
  return value;
}
function delay(milliseconds: number): Promise<void> { return new Promise((resolve) => setTimeout(resolve, milliseconds)); }
