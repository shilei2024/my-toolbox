import { NoEligibleProviderError, ProviderError, normalizeProviderError } from "../providers/errors.ts";
import type { ProviderSelectionPolicy } from "../providers/selection-policy.ts";
import type { ProductionGenerationResult } from "../pipeline/production-generation-pipeline.ts";
import type { JsonValue } from "../providers/types.ts";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import { MultiProviderExecutor, type MultiProviderExecutionOptions } from "../providers/multi-provider-executor.ts";
import { parseGenerationQueueJobData, type GenerationJobRepository, type GenerationQueueJobData, type GenerationQueueResult, type SafeQueueFailure } from "./types.ts";

export interface GenerationPipeline {
  execute: import("../pipeline/production-generation-pipeline.ts").ProductionGenerationPipeline["execute"];
}

export interface QueueExecutionContext {
  readonly queueJobId: string;
  readonly data: GenerationQueueJobData;
  readonly attemptsMade: number;
  readonly attemptsStarted: number;
  readonly maxAttempts: number;
  readonly signal?: AbortSignal;
  readonly updateProgress: (progress: number | Record<string, JsonValue>) => Promise<void>;
}

export class QueueExecutionError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly cancelled: boolean;
  constructor(code: string, message: string, retryable: boolean, cancelled = false, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "QueueExecutionError";
    this.code = code;
    this.retryable = retryable;
    this.cancelled = cancelled;
  }
}

export class GenerationQueueProcessor {
  readonly #repository: GenerationJobRepository;
  readonly #executor: MultiProviderExecutor;
  readonly #logger: StructuredLogger;
  constructor(repository: GenerationJobRepository, selection: ProviderSelectionPolicy, pipeline: GenerationPipeline, logger: StructuredLogger, options: MultiProviderExecutionOptions = {}) {
    this.#repository = repository;
    this.#executor = new MultiProviderExecutor(selection, pipeline, logger, options);
    this.#logger = logger;
  }

  async process(context: QueueExecutionContext): Promise<GenerationQueueResult> {
    const data = parseGenerationQueueJobData(context.data);
    const attemptNumber = context.attemptsStarted;
    const claim = await this.#repository.claim(data.jobId, { queueJobId: context.queueJobId, attemptNumber });
    if (claim.kind === "completed") return { jobId: data.jobId, state: "completed", assetUrls: claim.assetUrls, ...(claim.providerCode ? { providerCode: claim.providerCode } : {}) };
    if (claim.kind === "cancelled") throw new QueueExecutionError("job_cancelled", "Generation job was cancelled", false, true);

    const plan = claim.plan;
    const attemptId = plan.context.attemptId;
    if (context.signal?.aborted) {
      await this.#repository.markCancelled(data.jobId, attemptId, "queue_cancelled_before_execution");
      throw new QueueExecutionError("queue_cancelled", "Generation job was cancelled", false, true);
    }

    await context.updateProgress(5);
    let providerCode = "unselected";
    try {
      const result = await this.#executor.execute(plan.request, plan.bindings, { ...plan.context, ...(context.signal ? { signal: context.signal } : {}) }, async (attempt) => {
        providerCode = attempt.providerCode;
        await context.updateProgress(attempt.totalCall === 1
          ? { percent: 10, stage: "provider_selected", provider: providerCode }
          : { percent: 10, stage: "provider_fallback", provider: providerCode, attempt: attempt.providerAttempt });
      });
      await this.#repository.markCompleted(data.jobId, attemptId, result);
      await context.updateProgress(100);
      return toQueueResult(data.jobId, result);
    } catch (error) {
      const normalized = normalizeQueueFailure(error, providerCode);
      const cancelled = context.signal?.aborted || normalized.category === "cancelled";
      if (cancelled) {
        await this.#repository.markCancelled(data.jobId, attemptId, normalized.code);
        throw new QueueExecutionError(normalized.code, "Generation job was cancelled", false, true, error);
      }
      const willRetry = normalized.retryable && context.attemptsMade + 1 < context.maxAttempts;
      await this.#repository.markFailed(data.jobId, attemptId, normalized, willRetry);
      this.#logger.error("queue.execution_failed", { generationId: data.jobId, queueJobId: context.queueJobId, provider: providerCode, attemptNumber, willRetry, failureReason: normalized.code });
      throw new QueueExecutionError(normalized.code, normalized.message, willRetry, false, error);
    }
  }
}

function normalizeQueueFailure(error: unknown, providerCode: string): SafeQueueFailure {
  if (error instanceof NoEligibleProviderError) return { category: "configuration", code: "no_eligible_provider", message: "No eligible image provider is available", retryable: false };
  const providerError = error instanceof ProviderError ? error : normalizeProviderError(error, providerCode);
  return { category: providerError.category, code: providerError.code, message: providerError.message, retryable: providerError.retryable };
}

function toQueueResult(jobId: string, result: ProductionGenerationResult): GenerationQueueResult {
  return { jobId, state: "completed", providerCode: result.providerCode, assetUrls: result.assets.map((asset) => asset.url) };
}
