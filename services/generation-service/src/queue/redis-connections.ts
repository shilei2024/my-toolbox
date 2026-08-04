import { Redis } from "ioredis";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import type { GenerationQueueConfig } from "./config.ts";

export interface GenerationRedisConnections {
  readonly producer: Redis;
  readonly publisher: Redis;
  readonly worker: Redis;
  readonly subscriber: Redis;
}

export function createGenerationRedisConnections(config: GenerationQueueConfig, logger?: StructuredLogger): GenerationRedisConnections {
  return {
    producer: client(config.redisUrl, "generation-producer", { maxRetriesPerRequest: 1, enableOfflineQueue: false }, logger),
    publisher: client(config.redisUrl, "generation-cancel-publisher", { maxRetriesPerRequest: 1, enableOfflineQueue: false }, logger),
    worker: client(config.redisUrl, "generation-worker", { maxRetriesPerRequest: null, enableOfflineQueue: true }, logger),
    subscriber: client(config.redisUrl, "generation-cancel-subscriber", { maxRetriesPerRequest: null, enableOfflineQueue: true }, logger),
  };
}

function client(redisUrl: string, connectionName: string, options: { maxRetriesPerRequest: number | null; enableOfflineQueue: boolean }, logger?: StructuredLogger): Redis {
  const redis = new Redis(redisUrl, { ...options, connectionName, lazyConnect: false });
  redis.on("error", () => logger?.error("queue.redis_connection_error", { connection: connectionName, failureReason: "redis_error" }));
  return redis;
}
