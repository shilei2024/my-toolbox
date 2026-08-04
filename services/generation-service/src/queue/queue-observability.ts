import type { Queue } from "bullmq";
import type { Redis } from "ioredis";
import { GENERATION_QUEUE_JOB_NAME, type GenerationQueueJobData, type GenerationQueueResult } from "./types.ts";

export interface GenerationQueueSnapshot {
  readonly healthy: boolean;
  readonly redisLatencyMs: number;
  readonly workers: number;
  readonly waiting: number;
  readonly active: number;
  readonly delayed: number;
  readonly failed: number;
  readonly completed: number;
  readonly checkedAt: string;
}

export class GenerationQueueObservability {
  readonly #queue: Queue<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>;
  readonly #redis: Redis;
  constructor(queue: Queue<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>, redis: Redis) { this.#queue = queue; this.#redis = redis; }

  async snapshot(): Promise<GenerationQueueSnapshot> {
    const started = Date.now();
    try {
      await this.#redis.ping();
      const redisLatencyMs = Date.now() - started;
      const [counts, workers] = await Promise.all([this.#queue.getJobCounts("waiting", "active", "delayed", "failed", "completed"), this.#queue.getWorkersCount()]);
      return { healthy: true, redisLatencyMs, workers, waiting: counts.waiting ?? 0, active: counts.active ?? 0, delayed: counts.delayed ?? 0, failed: counts.failed ?? 0, completed: counts.completed ?? 0, checkedAt: new Date().toISOString() };
    } catch {
      return { healthy: false, redisLatencyMs: Date.now() - started, workers: 0, waiting: 0, active: 0, delayed: 0, failed: 0, completed: 0, checkedAt: new Date().toISOString() };
    }
  }
}

