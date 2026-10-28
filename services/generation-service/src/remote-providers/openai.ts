import { assertRequestSupported } from "../providers/capabilities.ts";
import { ProviderError } from "../providers/errors.ts";
import type { ImageProvider } from "../providers/image-provider.ts";
import type { CostEstimate, GenerationRequest, ProviderBinding, ProviderCallContext, ProviderCancelResult, ProviderDescriptor, ProviderHealthResult, ProviderStatusResult, ProviderSubmission } from "../providers/types.ts";
import { mapRemoteHttpError, isObject, requestRemoteJson, type RemoteProviderHttpConfig } from "./http.ts";
import { base64ImageOutput, combinedPrompt } from "./image-output.ts";
import { bindingCost, callSignal, configString, modelFrom, synchronousCancellation, synchronousStatus } from "./synchronous.ts";

export class OpenAIImageProvider implements ImageProvider {
  readonly descriptor: ProviderDescriptor = {
    code: "openai", displayName: "OpenAI Images", availability: "active", priority: 40,
    capabilities: { mediaTypes: ["image"], modes: ["text-to-image"], workflowKinds: [], models: [], minWidth: 512, maxWidth: 3840, minHeight: 512, maxHeight: 3840, maxOutputs: 1, supportsSeed: false, supportsCancellation: false, supportsStatusPolling: false },
  };
  readonly #config: RemoteProviderHttpConfig;
  readonly #fetcher: typeof fetch;

  constructor(config: RemoteProviderHttpConfig, fetcher: typeof fetch = fetch) { this.#config = config; this.#fetcher = fetcher; }

  async generate(request: GenerationRequest, binding: ProviderBinding, context: ProviderCallContext): Promise<ProviderSubmission> {
    assertRequestSupported(this.descriptor, request);
    validateDimensions(request);
    const model = modelFrom(binding, "openai");
    const quality = enumValue(configString(binding, "quality"), ["auto", "low", "medium", "high"], "auto", "quality");
    const moderation = enumValue(configString(binding, "moderation"), ["auto", "low"], "auto", "moderation");
    const background = enumValue(configString(binding, "background"), ["auto", "opaque"], "auto", "background");
    const signal = callSignal(context);
    try {
      const response = await requestRemoteJson(this.#config, "/images/generations", {
        method: "POST",
        headers: { authorization: `Bearer ${this.#config.apiKey}`, "content-type": "application/json" },
        body: JSON.stringify({ model, prompt: combinedPrompt(request.prompt, request.negativePrompt), size: `${request.width}x${request.height}`, n: 1, quality, moderation, background }),
        ...(signal ? { signal } : {}),
      }, this.#fetcher);
      const images = openAIImages(response.data);
      if (images.length !== 1) throw invalid("no_output", "OpenAI returned no image output");
      const output = await base64ImageOutput("openai", images[0]!, this.#config.maxResponseBytes);
      const externalRequestId = response.requestId ?? context.attemptId;
      return { externalRequestId, state: "succeeded", outputs: [output], providerMetadata: { model, outputCount: 1, upstreamRequestId: response.requestId ?? null } };
    } catch (error) { throw mapRemoteHttpError(error, "openai", openAIContentPolicy); }
  }

  async cancel(externalRequestId: string, _context: ProviderCallContext): Promise<ProviderCancelResult> { return synchronousCancellation(externalRequestId); }
  async getStatus(externalRequestId: string, _context: ProviderCallContext): Promise<ProviderStatusResult> { return synchronousStatus("openai", externalRequestId); }
  async estimateCost(_request: GenerationRequest, binding: ProviderBinding): Promise<CostEstimate> { return bindingCost(binding); }

  async healthCheck(context: ProviderCallContext): Promise<ProviderHealthResult> {
    const started = Date.now();
    const signal = callSignal(context);
    try {
      await requestRemoteJson(this.#config, "/models", { method: "GET", headers: { authorization: `Bearer ${this.#config.apiKey}` }, ...(signal ? { signal } : {}) }, this.#fetcher);
      return { healthy: true, latencyMs: Date.now() - started, checkedAt: new Date() };
    } catch { return { healthy: false, latencyMs: Date.now() - started, checkedAt: new Date(), message: "OpenAI health check failed" }; }
  }
}

function validateDimensions(request: GenerationRequest): void {
  const pixels = request.width * request.height;
  const ratio = Math.max(request.width, request.height) / Math.min(request.width, request.height);
  if (request.width % 16 !== 0 || request.height % 16 !== 0 || ratio > 3 || pixels < 655_360 || pixels > 8_294_400) {
    throw new ProviderError({ providerCode: "openai", category: "unsupported", code: "unsupported_dimensions", message: "OpenAI model does not support the requested dimensions", retryable: false });
  }
}

function openAIImages(value: unknown): string[] {
  if (!isObject(value) || !Array.isArray(value.data)) return [];
  return value.data.flatMap((item) => isObject(item) && typeof item.b64_json === "string" ? [item.b64_json] : []);
}

function openAIContentPolicy(value: unknown): boolean {
  if (!isObject(value)) return false;
  const error = isObject(value.error) ? value.error : value;
  return error.code === "moderation_blocked" || error.code === "content_policy_violation";
}

function enumValue<T extends string>(value: string | undefined, allowed: readonly T[], fallback: T, key: string): T {
  if (value === undefined) return fallback;
  if ((allowed as readonly string[]).includes(value)) return value as T;
  throw new ProviderError({ providerCode: "openai", category: "configuration", code: `invalid_${key}`, message: `OpenAI ${key} configuration is invalid`, retryable: false });
}

function invalid(code: string, message: string): ProviderError { return new ProviderError({ providerCode: "openai", category: "upstream", code, message, retryable: false }); }
