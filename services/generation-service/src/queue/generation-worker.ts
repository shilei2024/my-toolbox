import { UnrecoverableError, Worker, type Job } from "bullmq";
import type { Redis } from "ioredis";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import type { GenerationQueueConfig } from "./config.ts";
import { GenerationQueueProcessor, QueueExecutionError } from "./generation-queue-processor.ts";
import { parseCancellationCommand } from "./generation-queue-service.ts";
import { GENERATION_QUEUE_JOB_NAME, parseGenerationQueueJobData, type GenerationQueueJobData, type GenerationQueueResult } from "./types.ts";

export class GenerationWorkerRuntime {
  readonly #worker: Worker<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>;
  readonly #subscriber: Redis;
  readonly #config: GenerationQueueConfig;
  readonly #logger: StructuredLogger;
  #closed = false;
  #started = false;
  #runPromise: Promise<void> | undefined;

  constructor(processor: GenerationQueueProcessor, workerConnection: Redis, subscriber: Redis, config: GenerationQueueConfig, logger: StructuredLogger) {
    this.#subscriber = subscriber;
    this.#config = config;
    this.#logger = logger;
    this.#worker = new Worker<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>(
      config.queueName,
      async (job, _token, signal) => this.process(processor, job, signal),
      { connection: workerConnection, prefix: config.prefix, autorun: false, concurrency: config.concurrency, maxStalledCount: config.maxStalledCount, lockDuration: config.lockDurationMs, metrics: { maxDataPoints: 1000 } },
    );
    this.attachEvents();
    this.#subscriber.on("message", (channel, message) => {
      if (channel !== this.#config.cancellationChannel) return;
      const command = parseCancellationCommand(message);
      if (!command || command.queueName !== this.#config.queueName) return;
      const accepted = this.#worker.cancelJob(command.jobId, command.reason);
      this.#logger.info("queue.cancellation_received", { queueJobId: command.jobId, accepted, reason: command.reason });
    });
  }

  async start(): Promise<void> {
    if (this.#started) return;
    this.#started = true;
    await this.#subscriber.subscribe(this.#config.cancellationChannel);
    await this.#worker.waitUntilReady();
    this.#runPromise = this.#worker.run().catch(() => this.#logger.error("queue.worker_stopped_unexpectedly", { failureReason: "worker_run_failed" }));
  }

  async close(): Promise<void> {
    if (this.#closed) return;
    this.#closed = true;
    await this.#subscriber.unsubscribe(this.#config.cancellationChannel);
    const graceful = this.#worker.close(false).then(() => true);
    const completed = await Promise.race([graceful, timeout(this.#config.gracefulShutdownMs).then(() => false)]);
    if (!completed) {
      this.#worker.cancelAllJobs("graceful_shutdown_timeout");
      await this.#worker.close(true);
    }
    if (this.#runPromise) await this.#runPromise;
    await this.#subscriber.quit();
  }

  private async process(processor: GenerationQueueProcessor, job: Job<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>, signal?: AbortSignal): Promise<GenerationQueueResult> {
    try {
      const data = parseGenerationQueueJobData(job.data);
      return await processor.process({ queueJobId: job.id ?? data.jobId, data, attemptsMade: job.attemptsMade, attemptsStarted: job.attemptsStarted, maxAttempts: job.opts.attempts ?? 1, ...(signal ? { signal } : {}), updateProgress: async (progress) => job.updateProgress(progress) });
    } catch (error) {
      if (error instanceof QueueExecutionError && !error.retryable) throw new UnrecoverableError(`${error.code}: ${error.message}`);
      if (error instanceof Error) throw error;
      throw new UnrecoverableError("queue_unknown_error: Queue execution failed");
    }
  }

  private attachEvents(): void {
    this.#worker.on("completed", (job) => this.#logger.info("queue.job_completed", { queueJobId: job.id ?? "unknown", attemptsMade: job.attemptsMade }));
    this.#worker.on("failed", (job, error) => this.#logger.error("queue.job_failed", { queueJobId: job?.id ?? "unknown", attemptsMade: job?.attemptsMade ?? 0, failureReason: safeErrorCode(error) }));
    this.#worker.on("stalled", (jobId) => this.#logger.error("queue.job_stalled", { queueJobId: jobId }));
    this.#worker.on("lockRenewalFailed", (jobIds) => { for (const jobId of jobIds) this.#worker.cancelJob(jobId, "lock_renewal_failed"); this.#logger.error("queue.lock_renewal_failed", { jobIds }); });
    this.#worker.on("error", () => this.#logger.error("queue.worker_error", { failureReason: "worker_error" }));
  }
}

function safeErrorCode(error: Error): string { const match = /^([a-z0-9_]+)/i.exec(error.message); return match?.[1] ?? "queue_error"; }
function timeout(milliseconds: number): Promise<void> { return new Promise((resolve) => setTimeout(resolve, milliseconds)); }
