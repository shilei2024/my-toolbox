import { ProviderError } from "../providers/errors.ts";
import type { ImageProvider } from "../providers/image-provider.ts";
import type { GenerationRequest, ProviderBinding, ProviderCallContext } from "../providers/types.ts";
import type { StoredAsset } from "../storage/storage-provider.ts";
import type { ImagePersistenceService } from "./image-persistence.ts";
import type { PollingService } from "./polling-service.ts";
import type { StructuredLogger } from "./structured-logger.ts";

export interface ProductionGenerationResult { readonly externalRequestId: string; readonly assets: readonly StoredAsset[]; readonly providerCode: string; readonly providerMetadata: Readonly<Record<string, unknown>>; readonly generationDurationMs: number; readonly storageDurationMs: number }

export class ProductionGenerationPipeline {
  readonly #polling: PollingService;
  readonly #persistence: ImagePersistenceService;
  readonly #logger: StructuredLogger;
  constructor(polling: PollingService, persistence: ImagePersistenceService, logger: StructuredLogger) { this.#polling = polling; this.#persistence = persistence; this.#logger = logger; }
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
      const status = await this.#polling.wait(provider, submission, context);
      if (status.state !== "succeeded") throw new ProviderError({ providerCode: provider.descriptor.code, category: status.state === "cancelled" ? "cancelled" : "upstream", code: status.error?.code ?? `provider_${status.state}`, message: status.error?.message ?? "Provider generation failed", retryable: status.error?.retryable ?? false, externalRequestId: status.externalRequestId });
      const generatedAt = Date.now();
      const assets = await this.#persistence.persist(request.jobId, status.outputs);
      const finished = Date.now();
      this.#logger.info("generation.completed", { generationId: request.jobId, provider: provider.descriptor.code, workflow: request.workflow.workflowId, durationMs: finished - started, uploadDurationMs: finished - generatedAt, outputCount: assets.length });
      return { externalRequestId: status.externalRequestId, assets, providerCode: provider.descriptor.code, providerMetadata: status.providerMetadata, generationDurationMs: generatedAt - started, storageDurationMs: finished - generatedAt };
    } catch (error) {
      this.#logger.error("generation.failed", { generationId: request.jobId, provider: provider.descriptor.code, workflow: request.workflow.workflowId, durationMs: Date.now() - started, failureReason: error instanceof ProviderError ? error.code : "internal_error" });
      throw error;
    } finally {
      context.signal?.removeEventListener("abort", cancelUpstream);
      if (cancellation) await cancellation;
    }
  }
}
