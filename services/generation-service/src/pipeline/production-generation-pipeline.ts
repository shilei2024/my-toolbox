import { ProviderError } from "../providers/errors.ts";
import type { ImageProvider } from "../providers/image-provider.ts";
import type { GenerationRequest, ProviderBinding, ProviderCallContext } from "../providers/types.ts";
import type { GenerationPersistence, PersistedGenerationAsset } from "./media-persistence.ts";
import type { PollingService } from "./polling-service.ts";
import type { StructuredLogger } from "./structured-logger.ts";

export interface ProductionGenerationResult { readonly externalRequestId: string; readonly assets: readonly PersistedGenerationAsset[]; readonly providerCode: string; readonly providerMetadata: Readonly<Record<string, unknown>>; readonly actualCost?: number; readonly generationDurationMs: number; readonly storageDurationMs: number }

export class ProductionGenerationPipeline {
  readonly #polling: PollingService;
  readonly #persistence: GenerationPersistence;
  readonly #logger: StructuredLogger;
  constructor(polling: PollingService, persistence: GenerationPersistence, logger: StructuredLogger) { this.#polling = polling; this.#persistence = persistence; this.#logger = logger; }
  async execute(provider: ImageProvider, request: GenerationRequest, binding: ProviderBinding, context: ProviderCallContext): Promise<ProductionGenerationResult> {
    const started = Date.now();
    let cancellation: Promise<unknown> | undefined;
    let externalRequestId: string | undefined;
    const cancelUpstream = (): void => {
      if (!externalRequestId || cancellation) return;
      const { signal: _signal, ...cancelContext } = context;
      cancellation = provider.cancel(externalRequestId, cancelContext).catch(() => undefined);
    };
    context.signal?.addEventListener("abort", cancelUpstream, { once: true });
    this.#logger.info("generation.started", { generationId: request.jobId, provider: provider.descriptor.code, workflow: request.workflow.workflowId, workflowVersion: request.workflow.version });
    try {
      const submission = await provider.generate(request, binding, context);
      externalRequestId = submission.externalRequestId;
      if (context.signal?.aborted) {
        cancelUpstream();
        throw new ProviderError({ providerCode: provider.descriptor.code, category: "cancelled", code: "generation_cancelled", message: "Generation was cancelled", retryable: false, externalRequestId });
      }
      const status = await this.#polling.wait(provider, submission, context, binding.timeoutSeconds > 0 ? binding.timeoutSeconds * 1000 : undefined, binding.providerConfig.retryOnTimeout !== false);
      if (status.state !== "succeeded") throw new ProviderError({ providerCode: provider.descriptor.code, category: status.state === "cancelled" ? "cancelled" : "upstream", code: status.error?.code ?? `provider_${status.state}`, message: status.error?.message ?? "Provider generation failed", retryable: status.error?.retryable ?? false, externalRequestId: status.externalRequestId });
      const generatedAt = Date.now();
      const outputMediaType = request.mediaType ?? "image";
      if (status.outputs.some((output) => (output.mediaType ?? "image") !== outputMediaType)) throw new Error("Provider output media type does not match the generation request");
      const assets = await this.#persistence.persist(request.jobId, status.outputs, request.ownerKey);
      const finished = Date.now();
      this.#logger.info("generation.completed", { generationId: request.jobId, provider: provider.descriptor.code, workflow: request.workflow.workflowId, durationMs: finished - started, uploadDurationMs: finished - generatedAt, outputCount: assets.length });
      return { externalRequestId: status.externalRequestId, assets, providerCode: provider.descriptor.code, providerMetadata: status.providerMetadata, ...(status.actualCost === undefined ? {} : { actualCost: status.actualCost }), generationDurationMs: generatedAt - started, storageDurationMs: finished - generatedAt };
    } catch (error) {
      const detail = errorDetail(error);
      this.#logger.error("generation.failed", {
        generationId: request.jobId,
        provider: provider.descriptor.code,
        workflow: request.workflow.workflowId,
        durationMs: Date.now() - started,
        failureReason: error instanceof ProviderError ? error.code : "internal_error",
        ...(detail ? { failureDetail: detail } : {}),
      });
      throw error;
    } finally {
      context.signal?.removeEventListener("abort", cancelUpstream);
      if (cancellation) await cancellation;
    }
  }
}

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
