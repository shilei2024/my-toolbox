import { assertRequestSupported } from "./capabilities.ts";
import { ProviderError } from "./errors.ts";
import type { ImageProvider } from "./image-provider.ts";
import type {
  CostEstimate,
  GenerationRequest,
  JsonObject,
  ProviderBinding,
  ProviderCallContext,
  ProviderCancelResult,
  ProviderDescriptor,
  ProviderHealthResult,
  ProviderImageOutput,
  ProviderStatusResult,
  ProviderSubmission,
} from "./types.ts";

const ONE_PIXEL_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";

interface MockTask {
  readonly output: ProviderImageOutput;
  readonly readyAt: number;
  cancelled: boolean;
}

export interface MockProviderOptions {
  readonly code?: string;
  readonly availability?: "active" | "degraded" | "disabled";
  readonly priority?: number;
  readonly asynchronous?: boolean;
  readonly latencyMs?: number;
  readonly now?: () => number;
  readonly failure?: ProviderError;
}

export class MockImageProvider implements ImageProvider {
  readonly descriptor: ProviderDescriptor;
  readonly #asynchronous: boolean;
  readonly #latencyMs: number;
  readonly #now: () => number;
  readonly #failure: ProviderError | undefined;
  readonly #tasks = new Map<string, MockTask>();

  constructor(options: MockProviderOptions = {}) {
    this.#asynchronous = options.asynchronous ?? false;
    this.#latencyMs = options.latencyMs ?? 0;
    this.#now = options.now ?? Date.now;
    this.#failure = options.failure;
    this.descriptor = {
      code: options.code ?? "mock",
      displayName: "Mock Image Provider",
      availability: options.availability ?? "active",
      priority: options.priority ?? 100,
      capabilities: {
        modes: ["text-to-image", "image-to-image"],
        workflowKinds: [],
        models: ["mock-v1"],
        minWidth: 64,
        maxWidth: 4096,
        minHeight: 64,
        maxHeight: 4096,
        maxOutputs: 8,
        supportsSeed: true,
        supportsCancellation: true,
        supportsStatusPolling: true,
      },
    };
  }

  async generate(
    request: GenerationRequest,
    binding: ProviderBinding,
    context: ProviderCallContext,
  ): Promise<ProviderSubmission> {
    assertRequestSupported(this.descriptor, request);
    if (context.signal?.aborted) {
      throw new ProviderError({
        providerCode: this.descriptor.code,
        category: "cancelled",
        code: "request_aborted",
        message: "Provider request was cancelled",
      });
    }
    if (this.#failure) throw this.#failure;

    const externalRequestId = `mock-${context.attemptId}`;
    const output: ProviderImageOutput = {
      kind: "base64",
      data: ONE_PIXEL_PNG,
      mimeType: "image/png",
      width: request.width,
      height: request.height,
      ...(request.seed === undefined ? {} : { seed: request.seed }),
    };
    const providerMetadata: JsonObject = {
      mock: true,
      workflowRef: binding.providerWorkflowRef ?? null,
      model: binding.providerModel ?? "mock-v1",
    };
    if (!this.#asynchronous) {
      return { externalRequestId, state: "succeeded", outputs: [output], providerMetadata, actualCost: 0 };
    }
    this.#tasks.set(externalRequestId, {
      output,
      readyAt: this.#now() + this.#latencyMs,
      cancelled: false,
    });
    return { externalRequestId, state: "queued", outputs: [], providerMetadata, actualCost: 0 };
  }

  async cancel(externalRequestId: string, _context: ProviderCallContext): Promise<ProviderCancelResult> {
    const task = this.#tasks.get(externalRequestId);
    if (!task) return { externalRequestId, accepted: false, state: "failed" };
    task.cancelled = true;
    return { externalRequestId, accepted: true, state: "cancelled" };
  }

  async getStatus(externalRequestId: string, _context: ProviderCallContext): Promise<ProviderStatusResult> {
    const task = this.#tasks.get(externalRequestId);
    if (!task) {
      throw new ProviderError({
        providerCode: this.descriptor.code,
        category: "validation",
        code: "unknown_external_request",
        message: "Mock task does not exist",
      });
    }
    if (task.cancelled) {
      return { externalRequestId, state: "cancelled", outputs: [], providerMetadata: { mock: true }, actualCost: 0 };
    }
    if (this.#now() < task.readyAt) {
      return { externalRequestId, state: "running", progress: 0.5, outputs: [], providerMetadata: { mock: true }, actualCost: 0 };
    }
    return { externalRequestId, state: "succeeded", progress: 1, outputs: [task.output], providerMetadata: { mock: true }, actualCost: 0 };
  }

  async healthCheck(_context: ProviderCallContext): Promise<ProviderHealthResult> {
    return {
      healthy: this.descriptor.availability !== "disabled",
      latencyMs: 0,
      checkedAt: new Date(this.#now()),
      ...(this.descriptor.availability === "disabled" ? { message: "Mock provider is disabled" } : {}),
    };
  }

  async estimateCost(_request: GenerationRequest, _binding: ProviderBinding): Promise<CostEstimate> {
    return { amount: 0, currency: "USD", estimated: true };
  }
}
