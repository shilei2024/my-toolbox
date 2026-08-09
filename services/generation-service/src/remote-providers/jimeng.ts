import { assertRequestSupported } from "../providers/capabilities.ts";
import { ProviderError } from "../providers/errors.ts";
import type { ImageProvider } from "../providers/image-provider.ts";
import type { CostEstimate, GenerationRequest, ProviderBinding, ProviderCallContext, ProviderCancelResult, ProviderDescriptor, ProviderHealthResult, ProviderImageOutput, ProviderStatusResult, ProviderSubmission } from "../providers/types.ts";
import { isObject, mapRemoteHttpError, requestRemoteJson, type RemoteProviderHttpConfig } from "./http.ts";
import { base64ImageOutput, combinedPrompt } from "./image-output.ts";
import { bindingCost, callSignal, configBoolean, configNumber, configString, modelFrom, synchronousCancellation, synchronousStatus } from "./synchronous.ts";

// Seedream 4.x no longer accepts 1K images: the Ark API requires the total
// pixel count to stay inside [2560x1440, 4096x4096] while the aspect ratio
// remains within [1/16, 16]. Requests below the floor are scaled up
// proportionally so the user-chosen aspect ratio is preserved.
const SEEDREAM_MIN_TOTAL_PIXELS = 3_686_400; // 2560x1440
const SEEDREAM_MAX_TOTAL_PIXELS = 16_777_216; // 4096x4096
const SEEDREAM_MAX_EDGE = 4096;
const SEEDREAM_GRID = 8;

export class JimengImageProvider implements ImageProvider {
  readonly descriptor: ProviderDescriptor = {
    code: "jimeng", displayName: "即梦 / Seedream", availability: "active", priority: 30,
    capabilities: { modes: ["text-to-image"], workflowKinds: [], models: [], minWidth: 512, maxWidth: 4096, minHeight: 512, maxHeight: 4096, maxOutputs: 8, supportsSeed: true, supportsCancellation: false, supportsStatusPolling: false },
  };
  readonly #config: RemoteProviderHttpConfig;
  readonly #fetcher: typeof fetch;
  constructor(config: RemoteProviderHttpConfig, fetcher: typeof fetch = fetch) { this.#config = config; this.#fetcher = fetcher; }

  async generate(request: GenerationRequest, binding: ProviderBinding, context: ProviderCallContext): Promise<ProviderSubmission> {
    assertRequestSupported(this.descriptor, request);
    const model = modelFrom(binding, "jimeng");
    const guidanceScale = configNumber(binding, "guidanceScale");
    if (guidanceScale !== undefined && (guidanceScale < 1 || guidanceScale > 10)) throw configuration("invalid_guidance_scale", "Jimeng guidanceScale must be between 1 and 10");
    const optimizeMode = configString(binding, "optimizePromptMode");
    if (optimizeMode !== undefined && !["standard", "fast"].includes(optimizeMode)) throw configuration("invalid_optimize_mode", "Jimeng optimizePromptMode is invalid");
    // Seedream returns one image per call. Fan out for count > 1 so the
    // platform contract (count 1-8) works even though the API is single-output;
    // a user-provided seed becomes seed + index so each image is reproducible
    // and distinct.
    const watermark = configBoolean(binding, "watermark") ?? true;
    const outputs: ProviderImageOutput[] = [];
    let externalRequestId = context.attemptId;
    let upstreamRequestId: string | null = null;
    try {
      for (let index = 0; index < request.count; index += 1) {
        const body = {
          model,
          prompt: combinedPrompt(request.prompt, request.negativePrompt),
          size: seedreamSize(request.width, request.height),
          sequential_image_generation: "disabled",
          stream: false,
          response_format: "b64_json",
          watermark,
          ...(request.seed === undefined ? {} : { seed: request.seed + index }),
          ...(guidanceScale === undefined ? {} : { guidance_scale: guidanceScale }),
          ...(optimizeMode === undefined ? {} : { optimize_prompt_options: { mode: optimizeMode } }),
        };
        const signal = callSignal(context);
        const response = await requestRemoteJson(this.#config, "/images/generations", {
          method: "POST", headers: { authorization: `Bearer ${this.#config.apiKey}`, "content-type": "application/json" }, body: JSON.stringify(body),
          ...(signal ? { signal } : {}),
        }, this.#fetcher);
        const images = jimengImages(response.data);
        if (images.length !== 1) throw new ProviderError({ providerCode: "jimeng", category: "upstream", code: "no_output", message: "Jimeng returned no image output", retryable: false });
        outputs.push(await base64ImageOutput("jimeng", images[0]!, this.#config.maxResponseBytes));
        if (response.requestId) {
          externalRequestId = response.requestId;
          upstreamRequestId = response.requestId;
        }
      }
      return { externalRequestId, state: "succeeded", outputs, providerMetadata: { model, outputCount: outputs.length, upstreamRequestId } };
    } catch (error) { throw mapRemoteHttpError(error, "jimeng", jimengContentPolicy); }
  }

  async cancel(externalRequestId: string, _context: ProviderCallContext): Promise<ProviderCancelResult> { return synchronousCancellation(externalRequestId); }
  async getStatus(externalRequestId: string, _context: ProviderCallContext): Promise<ProviderStatusResult> { return synchronousStatus("jimeng", externalRequestId); }
  async estimateCost(_request: GenerationRequest, binding: ProviderBinding): Promise<CostEstimate> { return bindingCost(binding); }
  async healthCheck(context: ProviderCallContext): Promise<ProviderHealthResult> {
    const started = Date.now();
    const signal = callSignal(context);
    try {
      await requestRemoteJson(this.#config, "/models", { method: "GET", headers: { authorization: `Bearer ${this.#config.apiKey}` }, ...(signal ? { signal } : {}) }, this.#fetcher);
      return { healthy: true, latencyMs: Date.now() - started, checkedAt: new Date() };
    } catch { return { healthy: false, latencyMs: Date.now() - started, checkedAt: new Date(), message: "Jimeng health check failed" }; }
  }
}

function jimengImages(value: unknown): string[] { if (!isObject(value) || !Array.isArray(value.data)) return []; return value.data.flatMap((item) => isObject(item) && typeof item.b64_json === "string" ? [item.b64_json] : []); }
function jimengContentPolicy(value: unknown): boolean { if (!isObject(value)) return false; const error = isObject(value.error) ? value.error : value; return typeof error.code === "string" && /risk|safety|moderation|content.*policy/i.test(error.code); }
function configuration(code: string, message: string): ProviderError { return new ProviderError({ providerCode: "jimeng", category: "configuration", code, message, retryable: false }); }

function seedreamSize(width: number, height: number): string {
  let w = width;
  let h = height;
  const area = w * h;
  if (area < SEEDREAM_MIN_TOTAL_PIXELS || area > SEEDREAM_MAX_TOTAL_PIXELS) {
    const target = area < SEEDREAM_MIN_TOTAL_PIXELS ? SEEDREAM_MIN_TOTAL_PIXELS : SEEDREAM_MAX_TOTAL_PIXELS;
    const scale = Math.sqrt(target / area);
    w = Math.round(w * scale);
    h = Math.round(h * scale);
  }
  const longEdge = Math.max(w, h);
  if (longEdge > SEEDREAM_MAX_EDGE) {
    const shortRatio = Math.min(w, h) / longEdge;
    if (w > h) {
      w = SEEDREAM_MAX_EDGE;
      h = Math.round(w * shortRatio);
    } else {
      h = SEEDREAM_MAX_EDGE;
      w = Math.round(h * shortRatio);
    }
  }
  w = Math.round(w / SEEDREAM_GRID) * SEEDREAM_GRID;
  h = Math.round(h / SEEDREAM_GRID) * SEEDREAM_GRID;
  if (w * h < SEEDREAM_MIN_TOTAL_PIXELS) {
    const needed = Math.ceil(SEEDREAM_MIN_TOTAL_PIXELS / Math.max(w, h) / SEEDREAM_GRID) * SEEDREAM_GRID;
    if (w < h) w = needed; else h = needed;
  }
  if (w * h > SEEDREAM_MAX_TOTAL_PIXELS) {
    const allowed = Math.floor(SEEDREAM_MAX_TOTAL_PIXELS / Math.max(w, h) / SEEDREAM_GRID) * SEEDREAM_GRID;
    if (w > h) h = allowed; else w = allowed;
  }
  return `${Math.min(w, SEEDREAM_MAX_EDGE)}x${Math.min(h, SEEDREAM_MAX_EDGE)}`;
}
