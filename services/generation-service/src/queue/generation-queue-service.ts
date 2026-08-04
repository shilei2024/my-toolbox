import { Queue, type JobState } from "bullmq";
import type { Redis } from "ioredis";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import type { GenerationQueueConfig } from "./config.ts";
import { GENERATION_QUEUE_JOB_NAME, QUEUE_SCHEMA_VERSION, parseGenerationQueueJobData, type GenerationQueueJobData, type GenerationQueueResult, type GenerationQueueStatus } from "./types.ts";

export interface EnqueueGenerationInput { readonly jobId: string; readonly requestId: string; readonly priority?: number }
export interface QueueReceipt { readonly jobId: string; readonly queueName: string }
export interface CancellationReceipt { readonly jobId: string; readonly accepted: boolean; readonly mode: "removed" | "signalled" | "terminal" | "missing" }

export interface CancellationCommand { readonly schemaVersion: 1; readonly queueName: string; readonly jobId: string; readonly reason: string }

export class GenerationQueueService {
  readonly #queue: Queue<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>;
  readonly #publisher: Redis;
  readonly #config: GenerationQueueConfig;
  constructor(queue: Queue<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>, publisher: Redis, config: GenerationQueueConfig) {
    this.#queue = queue;
    this.#publisher = publisher;
    this.#config = config;
  }

  async enqueue(input: EnqueueGenerationInput): Promise<QueueReceipt> {
    const data = parseGenerationQueueJobData({ schemaVersion: QUEUE_SCHEMA_VERSION, jobId: input.jobId, requestId: input.requestId, enqueuedAt: new Date().toISOString() });
    const job = await this.#queue.add(GENERATION_QUEUE_JOB_NAME, data, {
      jobId: data.jobId,
      attempts: this.#config.attempts,
      backoff: { type: "exponential", delay: this.#config.backoffMs },
      ...(input.priority === undefined ? {} : { priority: input.priority }),
      removeOnComplete: { age: this.#config.retentionAgeSeconds, count: this.#config.completedRetentionCount },
      removeOnFail: { age: this.#config.retentionAgeSeconds, count: this.#config.failedRetentionCount },
      keepLogs: 50,
      stackTraceLimit: 3,
      sizeLimit: 4096,
    });
    return { jobId: job.id ?? data.jobId, queueName: this.#config.queueName };
  }

  async getStatus(jobId: string): Promise<GenerationQueueStatus> {
    const job = await this.#queue.getJob(jobId);
    if (!job) return { jobId, state: "unknown", progress: 0, attemptsMade: 0 };
    const state = await job.getState();
    return {
      jobId,
      state: publicState(state),
      progress: typeof job.progress === "number" || isObject(job.progress) ? job.progress : 0,
      attemptsMade: job.attemptsMade,
      ...(job.failedReason ? { failedReason: safeFailure(job.failedReason) } : {}),
    };
  }

  async requestCancellation(jobId: string, reason = "user_requested"): Promise<CancellationReceipt> {
    assertSafeToken(jobId, "job id");
    assertSafeToken(reason, "cancellation reason");
    const job = await this.#queue.getJob(jobId);
    if (!job) return { jobId, accepted: false, mode: "missing" };
    const state = await job.getState();
    if (new Set<JobState>(["waiting", "delayed", "prioritized", "waiting-children"]).has(state as JobState)) {
      await job.remove();
      return { jobId, accepted: true, mode: "removed" };
    }
    if (state === "active") {
      const command: CancellationCommand = { schemaVersion: 1, queueName: this.#config.queueName, jobId, reason };
      await this.#publisher.publish(this.#config.cancellationChannel, JSON.stringify(command));
      return { jobId, accepted: true, mode: "signalled" };
    }
    return { jobId, accepted: false, mode: "terminal" };
  }

  async close(): Promise<void> {
    await Promise.allSettled([this.#queue.close(), this.#publisher.quit()]);
  }
}

export function createGenerationQueue(connection: Redis, config: GenerationQueueConfig, logger?: StructuredLogger): Queue<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME> {
  const queue = new Queue<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>(config.queueName, { connection, prefix: config.prefix });
  queue.on("error", () => logger?.error("queue.producer_error", { failureReason: "redis_error" }));
  return queue;
}

export function parseCancellationCommand(value: string): CancellationCommand | undefined {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!isObject(parsed) || parsed.schemaVersion !== 1 || typeof parsed.queueName !== "string" || typeof parsed.jobId !== "string" || typeof parsed.reason !== "string") return undefined;
    const allowed = new Set(["schemaVersion", "queueName", "jobId", "reason"]);
    if (Object.keys(parsed).some((key) => !allowed.has(key))) return undefined;
    assertSafeToken(parsed.queueName, "queue name");
    assertSafeToken(parsed.jobId, "job id");
    assertSafeToken(parsed.reason, "reason");
    return { schemaVersion: 1, queueName: parsed.queueName, jobId: parsed.jobId, reason: parsed.reason };
  } catch { return undefined; }
}

function publicState(state: JobState | "unknown"): GenerationQueueStatus["state"] {
  if (state === "active") return "running";
  if (state === "waiting" || state === "prioritized" || state === "waiting-children") return "waiting";
  if (state === "delayed") return "delayed";
  if (state === "completed") return "completed";
  if (state === "failed") return "failed";
  return "unknown";
}
function safeFailure(value: string): string { return value.replace(/[\r\n]/g, " ").slice(0, 256); }
function isObject(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function assertSafeToken(value: string, label: string): void { if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(value)) throw new Error(`Invalid ${label}`); }
