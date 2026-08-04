import assert from "node:assert/strict";
import test from "node:test";
import type { Queue } from "bullmq";
import type { Redis } from "ioredis";

import { loadGenerationQueueConfig, QueueConfigurationError, type GenerationQueueConfig } from "../src/queue/config.ts";
import { GenerationQueueProcessor, QueueExecutionError } from "../src/queue/generation-queue-processor.ts";
import { GenerationQueueService, parseCancellationCommand } from "../src/queue/generation-queue-service.ts";
import { GenerationOutboxDispatcher, type GenerationOutboxEvent } from "../src/queue/outbox-dispatcher.ts";
import { GenerationQueueObservability } from "../src/queue/queue-observability.ts";
import { GENERATION_QUEUE_JOB_NAME, parseGenerationQueueJobData, QueuePayloadError, type GenerationJobClaim, type GenerationJobRepository, type GenerationQueueJobData, type GenerationQueueResult, type SafeQueueFailure } from "../src/queue/types.ts";
import { ProductionGenerationPipeline } from "../src/pipeline/production-generation-pipeline.ts";
import { PollingService } from "../src/pipeline/polling-service.ts";
import { ProviderError } from "../src/providers/errors.ts";
import { MockImageProvider } from "../src/providers/mock.provider.ts";
import { ProviderRegistry } from "../src/providers/registry.ts";
import { ProviderSelectionPolicy } from "../src/providers/selection-policy.ts";
import type { GenerationRequest, ProviderBinding, ProviderCallContext } from "../src/providers/types.ts";

const request: GenerationRequest = {
  jobId: "job-queue-1",
  workflow: { workflowId: "portrait", workflowVersionId: "workflow-version-1", version: 1, kind: "portrait" },
  mode: "text-to-image",
  prompt: "private prompt that must not enter Redis",
  negativePrompt: "",
  width: 1024,
  height: 1024,
  count: 1,
  seed: 17,
  parameters: {},
};
const binding: ProviderBinding = { id: "binding-mock", providerCode: "mock", workflowVersionId: request.workflow.workflowVersionId, providerConfig: {}, priority: 1, timeoutSeconds: 300, maxAttempts: 3, enabled: true };
const callContext: ProviderCallContext = { requestId: "request-queue-1", attemptId: "attempt-queue-1" };

test("queue configuration is environment-only and validates Redis and worker limits", () => {
  assert.throws(() => loadGenerationQueueConfig({}), QueueConfigurationError);
  assert.throws(() => loadGenerationQueueConfig(queueEnv({ REDIS_URL: "https://redis.example" })), (error) => error instanceof QueueConfigurationError && error.key === "REDIS_URL");
  const config = loadGenerationQueueConfig(queueEnv());
  assert.equal(config.queueName, "image-generation");
  assert.equal(config.attempts, 3);
  assert.equal(config.concurrency, 2);
});

test("Redis payload contains identifiers only and rejects prompt or provider fields", () => {
  const payload = parseGenerationQueueJobData({ schemaVersion: 1, jobId: "job-1", requestId: "request-1", enqueuedAt: new Date().toISOString() });
  assert.deepEqual(Object.keys(payload).sort(), ["enqueuedAt", "jobId", "requestId", "schemaVersion"]);
  assert.throws(() => parseGenerationQueueJobData({ ...payload, prompt: "secret" }), QueuePayloadError);
  assert.throws(() => parseGenerationQueueJobData({ ...payload, providerCode: "comfyui" }), QueuePayloadError);
});

test("queue producer uses the generation id as idempotent BullMQ job id", async () => {
  const config = queueConfig();
  const calls: Array<{ name: string; data: GenerationQueueJobData; options: Record<string, unknown> }> = [];
  const job = fakeJob("waiting");
  const queue = {
    async add(name: string, data: GenerationQueueJobData, options: Record<string, unknown>) { calls.push({ name, data, options }); return job; },
    async getJob() { return job; },
    async close() { return undefined; },
  } as unknown as Queue<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>;
  const published: string[] = [];
  const publisher = { async publish(_channel: string, message: string) { published.push(message); return 1; }, async quit() { return "OK"; } } as unknown as Redis;
  const service = new GenerationQueueService(queue, publisher, config);
  const receipt = await service.enqueue({ jobId: "job-queue-1", requestId: "request-queue-1", priority: 20 });
  assert.equal(receipt.jobId, "job-queue-1");
  assert.equal(calls[0]?.name, "generate");
  assert.equal(calls[0]?.options.jobId, "job-queue-1");
  assert.deepEqual(Object.keys(calls[0]?.data ?? {}).sort(), ["enqueuedAt", "jobId", "requestId", "schemaVersion"]);
  assert.deepEqual(calls[0]?.options.backoff, { type: "exponential", delay: 1000 });
  assert.equal(published.length, 0);
});

test("transactional outbox publishing retries without losing or duplicating generation ids", async () => {
  const events: GenerationOutboxEvent[] = [
    { id: "event-1", aggregateId: "job-queue-1", eventType: "generation.requested", payload: { requestId: "request-queue-1", priority: 10 }, attempts: 0 },
    { id: "event-2", aggregateId: "job-queue-2", eventType: "generation.requested", payload: { requestId: "request-queue-2" }, attempts: 2 },
  ];
  const marked: string[] = [];
  const rescheduled: Array<{ id: string; at: Date; error: string }> = [];
  const repository = { async claimBatch(limit: number) { return events.slice(0, limit); }, async markPublished(id: string) { marked.push(id); }, async reschedule(id: string, at: Date, error: string) { rescheduled.push({ id, at, error }); } };
  const enqueued: string[] = [];
  const queue = { async enqueue(input: { jobId: string }) { enqueued.push(input.jobId); if (input.jobId === "job-queue-2") throw new Error("redis down"); return { jobId: input.jobId, queueName: "image-generation" }; } };
  const dispatcher = new GenerationOutboxDispatcher(repository, queue, { batchSize: 10, retryBaseMs: 1000, retryMaxMs: 10000 }, { info() { return undefined; }, error() { return undefined; } });
  const now = new Date("2026-08-02T00:00:00.000Z");
  assert.deepEqual(await dispatcher.runOnce(now), { claimed: 2, published: 1, rescheduled: 1 });
  assert.deepEqual(enqueued, ["job-queue-1", "job-queue-2"]);
  assert.deepEqual(marked, ["event-1"]);
  assert.equal(rescheduled[0]?.at.toISOString(), "2026-08-02T00:00:04.000Z");
  assert.equal(rescheduled[0]?.error, "queue_publish_failed");
});

test("cancellation removes waiting jobs and signals active jobs across workers", async () => {
  const config = queueConfig();
  const published: string[] = [];
  let current = fakeJob("waiting");
  const queue = { async add() { return current; }, async getJob() { return current; }, async close() { return undefined; } } as unknown as Queue<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>;
  const publisher = { async publish(_channel: string, message: string) { published.push(message); return 1; }, async quit() { return "OK"; } } as unknown as Redis;
  const service = new GenerationQueueService(queue, publisher, config);
  assert.deepEqual(await service.requestCancellation("job-queue-1"), { jobId: "job-queue-1", accepted: true, mode: "removed" });
  assert.equal(current.removed, true);
  current = fakeJob("active");
  assert.deepEqual(await service.requestCancellation("job-queue-1"), { jobId: "job-queue-1", accepted: true, mode: "signalled" });
  assert.deepEqual(parseCancellationCommand(published[0] ?? ""), { schemaVersion: 1, queueName: "image-generation", jobId: "job-queue-1", reason: "user_requested" });
  assert.equal(parseCancellationCommand(JSON.stringify({ schemaVersion: 1, queueName: "x", jobId: "x", reason: "x", prompt: "leak" })), undefined);
});

test("queue observability reports bounded operational counts without job payloads", async () => {
  const queue = { async getJobCounts() { return { waiting: 4, active: 2, delayed: 1, failed: 3, completed: 9 }; }, async getWorkersCount() { return 2; } } as unknown as Queue<GenerationQueueJobData, GenerationQueueResult, typeof GENERATION_QUEUE_JOB_NAME>;
  const redis = { async ping() { return "PONG"; } } as unknown as Redis;
  const snapshot = await new GenerationQueueObservability(queue, redis).snapshot();
  assert.equal(snapshot.healthy, true);
  assert.equal(snapshot.workers, 2);
  assert.equal(snapshot.waiting, 4);
  assert.equal("prompt" in snapshot, false);
});

test("worker processor atomically claims, selects and completes a generation", async () => {
  const repository = new FakeRepository({ kind: "execute", plan: { request, bindings: [binding], context: callContext } });
  const selection = selectionPolicy();
  const pipelineResult = { externalRequestId: "external-1", assets: [{ storageProvider: "tencent_cos", bucket: "bucket", region: "ap-shanghai", objectKey: "images/jobs/job-queue-1/0.png", url: "https://cos.example/image.png", mimeType: "image/png", byteSize: 68, width: 1024, height: 1024, sha256: "a".repeat(64) }], providerCode: "mock", providerMetadata: {}, generationDurationMs: 50, storageDurationMs: 10 };
  const pipeline = { async execute() { return pipelineResult; } };
  const logs: unknown[] = [];
  const processor = new GenerationQueueProcessor(repository, selection, pipeline, { info() { return undefined; }, error(event, fields) { logs.push({ event, fields }); } });
  const progress: unknown[] = [];
  const result = await processor.process(executionContext(async (value) => { progress.push(value); }));
  assert.deepEqual(result, { jobId: "job-queue-1", state: "completed", providerCode: "mock", assetUrls: ["https://cos.example/image.png"] });
  assert.equal(repository.completed.length, 1);
  assert.equal(repository.failures.length, 0);
  assert.deepEqual(progress, [5, { percent: 10, stage: "provider_selected", provider: "mock" }, 100]);
  assert.equal(logs.length, 0);
});

test("retryable provider errors return to BullMQ until the configured attempt limit", async () => {
  const repository = new FakeRepository({ kind: "execute", plan: { request, bindings: [binding], context: callContext } });
  const pipeline = { async execute() { throw new ProviderError({ providerCode: "mock", category: "unavailable", code: "provider_down", message: "Provider is temporarily unavailable" }); } };
  const processor = new GenerationQueueProcessor(repository, selectionPolicy(), pipeline, { info() { return undefined; }, error() { return undefined; } });
  await assert.rejects(processor.process(executionContext(async () => undefined)), (error) => error instanceof QueueExecutionError && error.retryable && error.code === "provider_down");
  assert.equal(repository.failures[0]?.willRetry, true);

  const finalContext = executionContext(async () => undefined, { attemptsMade: 2, maxAttempts: 3 });
  await assert.rejects(processor.process(finalContext), (error) => error instanceof QueueExecutionError && !error.retryable);
  assert.equal(repository.failures[1]?.willRetry, false);
});

test("already completed database jobs short-circuit duplicate at-least-once delivery", async () => {
  const repository = new FakeRepository({ kind: "completed", providerCode: "comfyui", assetUrls: ["https://cos.example/existing.png"] });
  const pipeline = { async execute(): Promise<never> { throw new Error("must not execute"); } };
  const processor = new GenerationQueueProcessor(repository, selectionPolicy(), pipeline, { info() { return undefined; }, error() { return undefined; } });
  assert.deepEqual(await processor.process(executionContext(async () => undefined)), { jobId: "job-queue-1", state: "completed", providerCode: "comfyui", assetUrls: ["https://cos.example/existing.png"] });
  assert.equal(repository.completed.length, 0);
});

test("an aborted production pipeline cancels the submitted upstream provider", async () => {
  const controller = new AbortController();
  let cancelled = 0;
  const provider = new MockImageProvider({ asynchronous: true, latencyMs: 60_000 });
  const originalGenerate = provider.generate.bind(provider);
  provider.generate = async (...args) => { const submission = await originalGenerate(...args); controller.abort("user_requested"); return submission; };
  const originalCancel = provider.cancel.bind(provider);
  provider.cancel = async (...args) => { cancelled += 1; return originalCancel(...args); };
  const pipeline = new ProductionGenerationPipeline(new PollingService({ intervalMs: 1, maxAttempts: 2 }, async () => undefined), { async persist() { return []; } } as never, { info() { return undefined; }, error() { return undefined; } });
  await assert.rejects(pipeline.execute(provider, request, binding, { ...callContext, signal: controller.signal }), (error) => error instanceof ProviderError && error.category === "cancelled");
  assert.equal(cancelled, 1);
});

class FakeRepository implements GenerationJobRepository {
  readonly completed: unknown[] = [];
  readonly failures: Array<{ failure: SafeQueueFailure; willRetry: boolean }> = [];
  readonly cancelled: unknown[] = [];
  readonly #claim: GenerationJobClaim;
  constructor(claim: GenerationJobClaim) { this.#claim = claim; }
  async claim(): Promise<GenerationJobClaim> { return this.#claim; }
  async markProviderAttempt(_jobId: string, baseAttemptId: string): Promise<string> { return baseAttemptId; }
  async markCompleted(...args: unknown[]): Promise<void> { this.completed.push(args); }
  async markFailed(_jobId: string, _attemptId: string, failure: SafeQueueFailure, willRetry: boolean): Promise<void> { this.failures.push({ failure, willRetry }); }
  async markCancelled(...args: unknown[]): Promise<void> { this.cancelled.push(args); }
}

function selectionPolicy(): ProviderSelectionPolicy {
  const registry = new ProviderRegistry();
  registry.register(new MockImageProvider());
  return new ProviderSelectionPolicy(registry);
}

function executionContext(updateProgress: (value: number | Record<string, unknown>) => Promise<void>, overrides: Partial<{ attemptsMade: number; attemptsStarted: number; maxAttempts: number }> = {}) {
  return { queueJobId: "job-queue-1", data: { schemaVersion: 1 as const, jobId: "job-queue-1", requestId: "request-queue-1", enqueuedAt: new Date().toISOString() }, attemptsMade: 0, attemptsStarted: 1, maxAttempts: 3, updateProgress, ...overrides };
}

function fakeJob(state: string) {
  return { id: "job-queue-1", progress: 0, attemptsMade: 0, failedReason: "", removed: false, async getState() { return state; }, async remove() { this.removed = true; } };
}

function queueConfig(): GenerationQueueConfig {
  return { redisUrl: "redis://localhost:6379/0", prefix: "ai-image", queueName: "image-generation", cancellationChannel: "generation-cancel", concurrency: 2, attempts: 3, backoffMs: 1000, completedRetentionCount: 1000, failedRetentionCount: 5000, retentionAgeSeconds: 604800, maxStalledCount: 1, lockDurationMs: 30000, gracefulShutdownMs: 30000, outboxBatchSize: 100, outboxRetryBaseMs: 1000, outboxRetryMaxMs: 60000 };
}

function queueEnv(overrides: Record<string, string> = {}): NodeJS.ProcessEnv {
  return { REDIS_URL: "redis://localhost:6379/0", BULLMQ_PREFIX: "ai-image", BULLMQ_QUEUE_NAME: "image-generation", BULLMQ_CANCEL_CHANNEL: "generation-cancel", BULLMQ_CONCURRENCY: "2", BULLMQ_ATTEMPTS: "3", BULLMQ_BACKOFF_MS: "1000", BULLMQ_COMPLETED_RETENTION_COUNT: "1000", BULLMQ_FAILED_RETENTION_COUNT: "5000", BULLMQ_RETENTION_AGE_SECONDS: "604800", BULLMQ_MAX_STALLED_COUNT: "1", BULLMQ_LOCK_DURATION_MS: "30000", BULLMQ_GRACEFUL_SHUTDOWN_MS: "30000", GENERATION_OUTBOX_BATCH_SIZE: "100", GENERATION_OUTBOX_RETRY_BASE_MS: "1000", GENERATION_OUTBOX_RETRY_MAX_MS: "60000", ...overrides };
}
