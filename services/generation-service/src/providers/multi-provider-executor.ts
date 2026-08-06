import type { ProductionGenerationResult } from "../pipeline/production-generation-pipeline.ts";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import { NoEligibleProviderError, ProviderError, normalizeProviderError } from "./errors.ts";
import type { ProviderCandidate, ProviderSelectionPolicy } from "./selection-policy.ts";
import type { GenerationRequest, ProviderBinding, ProviderCallContext } from "./types.ts";

export interface ProviderGenerationPipeline {
  execute: import("../pipeline/production-generation-pipeline.ts").ProductionGenerationPipeline["execute"];
}

export interface MultiProviderExecutionOptions {
  readonly retryBaseMs?: number;
  readonly maxTotalCalls?: number;
  readonly sleep?: (milliseconds: number) => Promise<void>;
}

export interface ProviderAttemptEvent {
  readonly providerCode: string;
  readonly bindingId: string;
  readonly providerAttempt: number;
  readonly totalCall: number;
}

export class MultiProviderExecutor {
  readonly #selection: ProviderSelectionPolicy;
  readonly #pipeline: ProviderGenerationPipeline;
  readonly #logger: StructuredLogger;
  readonly #retryBaseMs: number;
  readonly #maxTotalCalls: number;
  readonly #sleep: (milliseconds: number) => Promise<void>;

  constructor(selection: ProviderSelectionPolicy, pipeline: ProviderGenerationPipeline, logger: StructuredLogger, options: MultiProviderExecutionOptions = {}) {
    this.#selection = selection;
    this.#pipeline = pipeline;
    this.#logger = logger;
    this.#retryBaseMs = options.retryBaseMs ?? 0;
    this.#maxTotalCalls = options.maxTotalCalls ?? 10;
    this.#sleep = options.sleep ?? ((milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)));
    if (!Number.isInteger(this.#retryBaseMs) || this.#retryBaseMs < 0) throw new TypeError("retryBaseMs must be a non-negative integer");
    if (!Number.isInteger(this.#maxTotalCalls) || this.#maxTotalCalls < 1) throw new TypeError("maxTotalCalls must be a positive integer");
  }

  async execute(request: GenerationRequest, bindings: readonly ProviderBinding[], context: ProviderCallContext, onAttempt: (event: ProviderAttemptEvent) => Promise<string | void> | string | void = () => undefined): Promise<ProductionGenerationResult> {
    const candidates = this.#selection.rank(request, bindings);
    if (candidates.length === 0) throw new NoEligibleProviderError();
    let totalCall = 0;
    const failedProviders: string[] = [];
    for (const candidate of candidates) {
      let lastError: ProviderError | undefined;
      const attempts = candidates.length === 1 ? 1 : Math.min(candidate.binding.maxAttempts, this.#maxTotalCalls - totalCall);
      for (let providerAttempt = 1; providerAttempt <= attempts; providerAttempt += 1) {
        if (context.signal?.aborted) throw cancelled(candidate);
        totalCall += 1;
        const recordedAttemptId = await onAttempt({ providerCode: candidate.provider.descriptor.code, bindingId: candidate.binding.id, providerAttempt, totalCall });
        const derivedAttemptId = providerAttempt === 1 && totalCall === 1 ? context.attemptId : childAttemptId(context.attemptId, candidate.provider.descriptor.code, providerAttempt, totalCall);
        const attemptContext = recordedAttemptId ? { ...context, attemptId: recordedAttemptId } : derivedAttemptId === context.attemptId ? context : { ...context, attemptId: derivedAttemptId };
        try { return await this.#pipeline.execute(candidate.provider, request, candidate.binding, attemptContext); }
        catch (error) {
          lastError = normalizeProviderError(error, candidate.provider.descriptor.code);
          const detail = errorDetail(lastError);
          this.#logger.error("provider.attempt_failed", {
            generationId: request.jobId,
            provider: candidate.provider.descriptor.code,
            providerAttempt,
            totalCall,
            failureReason: lastError.code,
            retryable: lastError.retryable,
            ...(detail ? { failureDetail: detail } : {}),
          });
          if (!lastError.retryable || providerAttempt >= attempts) break;
          const delay = Math.min(this.#retryBaseMs * 2 ** (providerAttempt - 1), 30_000);
          if (delay > 0) await this.#sleep(delay);
        }
      }
      if (!lastError) break;
      failedProviders.push(candidate.provider.descriptor.code);
      if (!mayFallback(lastError) || totalCall >= this.#maxTotalCalls) throw lastError;
      const nextProvider = nextCode(candidates, candidate);
      if (!nextProvider) {
        if (candidates.length === 1) throw lastError;
        break;
      }
      this.#logger.info("provider.fallback_selected", { generationId: request.jobId, failedProvider: candidate.provider.descriptor.code, nextProvider, failureReason: lastError.code });
    }
    throw new ProviderError({ providerCode: "generation_service", category: "unavailable", code: "all_providers_exhausted", message: "All eligible image providers are temporarily unavailable", retryable: false, cause: { failedProviders } });
  }
}

function mayFallback(error: ProviderError): boolean {
  if (error.category === "content_policy" || error.category === "validation" || error.category === "cancelled" || error.category === "unknown") return false;
  if (error.category === "timeout" && !error.retryable) return false;
  return error.retryable || error.category === "authentication" || error.category === "configuration" || error.category === "unsupported";
}

function cancelled(candidate: ProviderCandidate): ProviderError { return new ProviderError({ providerCode: candidate.provider.descriptor.code, category: "cancelled", code: "request_aborted", message: "Provider request was cancelled", retryable: false }); }
function nextCode(candidates: readonly ProviderCandidate[], current: ProviderCandidate): string | undefined { const index = candidates.indexOf(current); return candidates[index + 1]?.provider.descriptor.code; }
function childAttemptId(base: string, providerCode: string, providerAttempt: number, totalCall: number): string { return `${base}-${providerCode}-${providerAttempt}-${totalCall}`.slice(0, 128); }

function errorDetail(error: unknown): string | undefined {
  const messages: string[] = [];
  const seen = new Set<Error>();
  let current: unknown = error;
  while (current instanceof Error && !seen.has(current)) {
    seen.add(current);
    const message = current.message.trim();
    if (message) messages.push(message);
    current = current.cause;
  }
  const detail = messages.join(" | ").trim();
  return detail ? detail.slice(0, 500) : undefined;
}
