import { assertRequestSupported } from "../providers/capabilities.ts";
import { ProviderError } from "../providers/errors.ts";
import type { ImageProvider } from "../providers/image-provider.ts";
import type { CostEstimate, GenerationRequest, ProviderBinding, ProviderCallContext, ProviderCancelResult, ProviderDescriptor, ProviderHealthResult, ProviderStatusResult, ProviderSubmission } from "../providers/types.ts";
import { isObject, mapRemoteHttpError, requestRemoteJson, type RemoteProviderHttpConfig } from "./http.ts";
import { base64ImageOutput, combinedPrompt } from "./image-output.ts";
import { bindingCost, callSignal, configString, modelFrom, synchronousCancellation, synchronousStatus } from "./synchronous.ts";

const RATIOS = [[1, 1, "1:1"], [1, 4, "1:4"], [1, 8, "1:8"], [2, 3, "2:3"], [3, 2, "3:2"], [3, 4, "3:4"], [4, 1, "4:1"], [4, 3, "4:3"], [4, 5, "4:5"], [5, 4, "5:4"], [8, 1, "8:1"], [9, 16, "9:16"], [16, 9, "16:9"], [21, 9, "21:9"]] as const;

export class GeminiImageProvider implements ImageProvider {
  readonly descriptor: ProviderDescriptor = {
    code: "gemini", displayName: "Google Gemini Image", availability: "active", priority: 50,
    capabilities: { mediaTypes: ["image"], modes: ["text-to-image"], workflowKinds: [], models: [], minWidth: 512, maxWidth: 4096, minHeight: 512, maxHeight: 4096, maxOutputs: 1, supportsSeed: false, supportsCancellation: false, supportsStatusPolling: false },
  };
  readonly #config: RemoteProviderHttpConfig;
  readonly #fetcher: typeof fetch;
  constructor(config: RemoteProviderHttpConfig, fetcher: typeof fetch = fetch) { this.#config = config; this.#fetcher = fetcher; }

  async generate(request: GenerationRequest, binding: ProviderBinding, context: ProviderCallContext): Promise<ProviderSubmission> {
    assertRequestSupported(this.descriptor, request);
    const model = modelFrom(binding, "gemini");
    const aspectRatio = ratio(request.width, request.height);
    const imageSize = geminiImageSize(configString(binding, "imageSize"), Math.max(request.width, request.height));
    const signal = callSignal(context);
    try {
      const response = await requestRemoteJson(this.#config, `/models/${encodeURIComponent(model)}:generateContent`, {
        method: "POST",
        headers: { "x-goog-api-key": this.#config.apiKey, "content-type": "application/json" },
        body: JSON.stringify({ contents: [{ role: "user", parts: [{ text: combinedPrompt(request.prompt, request.negativePrompt) }] }], generationConfig: { responseModalities: ["IMAGE"], responseFormat: { image: { aspectRatio, imageSize } } } }),
        ...(signal ? { signal } : {}),
      }, this.#fetcher);
      if (geminiSafetyBlocked(response.data)) throw new ProviderError({ providerCode: "gemini", category: "content_policy", code: "content_policy_blocked", message: "Image generation was blocked by provider safety policy", retryable: false });
      const images = geminiImages(response.data);
      if (images.length !== 1) throw new ProviderError({ providerCode: "gemini", category: "upstream", code: "no_output", message: "Gemini returned no image output", retryable: false });
      const output = await base64ImageOutput("gemini", images[0]!, this.#config.maxResponseBytes);
      const externalRequestId = response.requestId ?? context.attemptId;
      return { externalRequestId, state: "succeeded", outputs: [output], providerMetadata: { model, outputCount: 1, aspectRatio, imageSize, upstreamRequestId: response.requestId ?? null } };
    } catch (error) { throw mapRemoteHttpError(error, "gemini", geminiSafetyBlocked); }
  }

  async cancel(externalRequestId: string, _context: ProviderCallContext): Promise<ProviderCancelResult> { return synchronousCancellation(externalRequestId); }
  async getStatus(externalRequestId: string, _context: ProviderCallContext): Promise<ProviderStatusResult> { return synchronousStatus("gemini", externalRequestId); }
  async estimateCost(_request: GenerationRequest, binding: ProviderBinding): Promise<CostEstimate> { return bindingCost(binding); }
  async healthCheck(context: ProviderCallContext): Promise<ProviderHealthResult> {
    const started = Date.now();
    const signal = callSignal(context);
    try {
      await requestRemoteJson(this.#config, "/models?pageSize=1", { method: "GET", headers: { "x-goog-api-key": this.#config.apiKey }, ...(signal ? { signal } : {}) }, this.#fetcher);
      return { healthy: true, latencyMs: Date.now() - started, checkedAt: new Date() };
    } catch { return { healthy: false, latencyMs: Date.now() - started, checkedAt: new Date(), message: "Gemini health check failed" }; }
  }
}

function ratio(width: number, height: number): string {
  const requested = width / height;
  const candidate = RATIOS.map(([w, h, label]) => ({ label, difference: Math.abs(requested - w / h) / requested })).sort((a, b) => a.difference - b.difference)[0];
  if (!candidate || candidate.difference > 0.02) throw new ProviderError({ providerCode: "gemini", category: "unsupported", code: "unsupported_aspect_ratio", message: "Gemini does not support the requested aspect ratio", retryable: false });
  return candidate.label;
}

function geminiImageSize(configured: string | undefined, longestEdge: number): string {
  const value = configured ?? (longestEdge <= 1024 ? "1K" : longestEdge <= 2048 ? "2K" : "4K");
  if (!["512", "1K", "2K", "4K"].includes(value)) throw new ProviderError({ providerCode: "gemini", category: "configuration", code: "invalid_image_size", message: "Gemini imageSize configuration is invalid", retryable: false });
  return value;
}

function geminiImages(value: unknown): string[] {
  if (!isObject(value) || !Array.isArray(value.candidates)) return [];
  return value.candidates.flatMap((candidate) => {
    if (!isObject(candidate) || !isObject(candidate.content) || !Array.isArray(candidate.content.parts)) return [];
    return candidate.content.parts.flatMap((part) => isObject(part) && isObject(part.inlineData) && typeof part.inlineData.data === "string" ? [part.inlineData.data] : []);
  });
}

function geminiSafetyBlocked(value: unknown): boolean {
  if (!isObject(value)) return false;
  if (isObject(value.promptFeedback) && typeof value.promptFeedback.blockReason === "string" && value.promptFeedback.blockReason !== "BLOCK_REASON_UNSPECIFIED") return true;
  if (Array.isArray(value.candidates) && value.candidates.some((candidate) => isObject(candidate) && typeof candidate.finishReason === "string" && ["SAFETY", "PROHIBITED_CONTENT", "IMAGE_SAFETY"].includes(candidate.finishReason))) return true;
  const error = isObject(value.error) ? value.error : value;
  return typeof error.code === "string" && /safety|policy|moderation/i.test(error.code);
}
