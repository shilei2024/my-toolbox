import { assertRequestSupported } from "../providers/capabilities.ts";
import { ProviderError } from "../providers/errors.ts";
import type { GenerationProvider } from "../providers/image-provider.ts";
import type { CostEstimate, GenerationRequest, ProviderBinding, ProviderCallContext, ProviderCancelResult, ProviderDescriptor, ProviderHealthResult, ProviderStatusResult, ProviderSubmission, ProviderVideoOutput } from "../providers/types.ts";
import { isObject, mapRemoteHttpError, requestRemoteJson, type RemoteProviderHttpConfig } from "./http.ts";
import { bindingCost, callSignal, configBoolean, configNumber, configString, modelFrom } from "./synchronous.ts";

interface VideoTaskContext { readonly width: number; readonly height: number; readonly durationSeconds: number; readonly model: string }

export class ArkVideoProvider implements GenerationProvider {
  readonly descriptor: ProviderDescriptor = {
    code: "ark-video",
    displayName: "火山方舟视频生成",
    availability: "active",
    priority: 60,
    capabilities: {
      mediaTypes: ["video"],
      modes: ["text-to-video"],
      workflowKinds: [],
      models: [],
      minWidth: 256,
      maxWidth: 4096,
      minHeight: 256,
      maxHeight: 4096,
      maxOutputs: 1,
      supportsSeed: true,
      supportsCancellation: true,
      supportsStatusPolling: true,
    },
  };
  readonly #config: RemoteProviderHttpConfig;
  readonly #fetcher: typeof fetch;
  readonly #tasks = new Map<string, VideoTaskContext>();

  constructor(config: RemoteProviderHttpConfig, fetcher: typeof fetch = fetch) {
    this.#config = config;
    this.#fetcher = fetcher;
  }

  async generate(request: GenerationRequest, binding: ProviderBinding, context: ProviderCallContext): Promise<ProviderSubmission> {
    assertRequestSupported(this.descriptor, request);
    if ((request.mediaType ?? "image") !== "video" || request.mode !== "text-to-video") throw invalid("unsupported_request", "Ark video requires a text-to-video request");
    const model = modelFrom(binding, "ark-video");
    const durationSeconds = duration(request, binding);
    const ratio = aspectRatio(request.width, request.height);
    const resolution = enumValue(configString(binding, "resolution"), ["480p", "720p", "1080p"] as const, request.height <= 480 || request.width <= 480 ? "480p" : "720p", "resolution");
    const body: Record<string, unknown> = {
      model,
      content: [{ type: "text", text: combinedPrompt(request.prompt, request.negativePrompt) }],
      ratio,
      duration: durationSeconds,
      resolution,
      watermark: configBoolean(binding, "watermark") ?? false,
      generate_audio: configBoolean(binding, "generateAudio") ?? false,
      ...(request.seed === undefined ? {} : { seed: request.seed }),
    };
    const signal = callSignal(context);
    try {
      const response = await requestRemoteJson(this.#config, "/contents/generations/tasks", {
        method: "POST",
        headers: { authorization: `Bearer ${this.#config.apiKey}`, "content-type": "application/json" },
        body: JSON.stringify(body),
        ...(signal ? { signal } : {}),
      }, this.#fetcher);
      const externalRequestId = taskId(response.data);
      this.#tasks.set(externalRequestId, { width: request.width, height: request.height, durationSeconds, model });
      return { externalRequestId, state: "queued", outputs: [], providerMetadata: { model, outputCount: 0, upstreamRequestId: response.requestId ?? null } };
    } catch (error) {
      throw mapRemoteHttpError(error, "ark-video", contentPolicyError);
    }
  }

  async getStatus(externalRequestId: string, context: ProviderCallContext): Promise<ProviderStatusResult> {
    const task = this.#tasks.get(externalRequestId);
    // Worker-restart resilience: the in-memory task map may be gone while the
    // upstream job is still running. Reconstruct from the durable request
    // metadata so we keep polling instead of failing the job (and refunding
    // credits) for an upstream task that is still executing.
    const recoveredTask: VideoTaskContext | undefined = task ?? (
      context.taskMetadata?.width && context.taskMetadata?.height
        ? { width: context.taskMetadata.width, height: context.taskMetadata.height, durationSeconds: context.taskMetadata.durationSeconds ?? 5, model: "unknown" }
        : undefined
    );
    if (!recoveredTask) throw new ProviderError({ providerCode: "ark-video", category: "timeout", code: "unknown_external_request", message: "Ark video task context is unavailable", retryable: true, externalRequestId });
    const signal = callSignal(context);
    try {
      const response = await requestRemoteJson(this.#config, `/contents/generations/tasks/${encodeURIComponent(externalRequestId)}`, {
        method: "GET",
        headers: { authorization: `Bearer ${this.#config.apiKey}`, "content-type": "application/json" },
        ...(signal ? { signal } : {}),
      }, this.#fetcher);
      const result = statusBody(response.data);
      if (result.status === "queued" || result.status === "running") {
        return { externalRequestId, state: result.status, ...(result.status === "running" ? { progress: 0.5 } : {}), outputs: [], providerMetadata: { model: recoveredTask.model, outputCount: 0 } };
      }
      if (result.status === "cancelled") return { externalRequestId, state: "cancelled", outputs: [], providerMetadata: { model: recoveredTask.model, outputCount: 0 } };
      if (result.status === "failed") {
        return { externalRequestId, state: "failed", outputs: [], providerMetadata: { model: recoveredTask.model, outputCount: 0 }, error: failure(result.error, externalRequestId) };
      }
      const url = videoUrl(result.content);
      const output: ProviderVideoOutput = { mediaType: "video", kind: "remote-url", url, mimeType: "video/mp4", width: recoveredTask.width, height: recoveredTask.height, durationSeconds: responseDuration(response.data) ?? recoveredTask.durationSeconds };
      if (task) this.#tasks.delete(externalRequestId);
      return { externalRequestId, state: "succeeded", progress: 1, outputs: [output], providerMetadata: { model: recoveredTask.model, outputCount: 1 } };
    } catch (error) {
      throw mapRemoteHttpError(error, "ark-video", contentPolicyError);
    }
  }

  async cancel(externalRequestId: string, context: ProviderCallContext): Promise<ProviderCancelResult> {
    const signal = callSignal(context);
    try {
      await requestRemoteJson(this.#config, `/contents/generations/tasks/${encodeURIComponent(externalRequestId)}`, {
        method: "DELETE",
        headers: { authorization: `Bearer ${this.#config.apiKey}`, "content-type": "application/json" },
        ...(signal ? { signal } : {}),
      }, this.#fetcher);
      this.#tasks.delete(externalRequestId);
      return { externalRequestId, accepted: true, state: "cancelled" };
    } catch (error) {
      const mapped = mapRemoteHttpError(error, "ark-video", contentPolicyError);
      if (mapped.statusCode === 400) return { externalRequestId, accepted: false, state: "running" };
      throw mapped;
    }
  }

  async healthCheck(context: ProviderCallContext): Promise<ProviderHealthResult> {
    const started = Date.now();
    const signal = callSignal(context);
    try {
      await requestRemoteJson(this.#config, "/models", { method: "GET", headers: { authorization: `Bearer ${this.#config.apiKey}` }, ...(signal ? { signal } : {}) }, this.#fetcher);
      return { healthy: true, latencyMs: Date.now() - started, checkedAt: new Date() };
    } catch {
      return { healthy: false, latencyMs: Date.now() - started, checkedAt: new Date(), message: "Ark video health check failed" };
    }
  }

  async estimateCost(_request: GenerationRequest, binding: ProviderBinding): Promise<CostEstimate> { return bindingCost(binding); }
}

function duration(request: GenerationRequest, binding: ProviderBinding): number {
  const value = typeof request.parameters.durationSeconds === "number" ? request.parameters.durationSeconds : configNumber(binding, "durationSeconds") ?? 5;
  if (!Number.isSafeInteger(value) || ![5, 10].includes(value)) throw invalid("unsupported_duration", "Ark video duration must be 5 or 10 seconds");
  return value;
}
function combinedPrompt(prompt: string, negativePrompt: string): string { return negativePrompt.trim() ? `${prompt}\n避免：${negativePrompt.trim()}` : prompt; }
function aspectRatio(width: number, height: number): "16:9" | "9:16" | "1:1" | "4:3" | "3:4" | "21:9" {
  const supported = [{ name: "21:9", value: 21 / 9 }, { name: "16:9", value: 16 / 9 }, { name: "4:3", value: 4 / 3 }, { name: "1:1", value: 1 }, { name: "3:4", value: 3 / 4 }, { name: "9:16", value: 9 / 16 }] as const;
  return supported.reduce((best, item) => Math.abs(item.value - width / height) < Math.abs(best.value - width / height) ? item : best).name;
}
function taskId(value: unknown): string { if (!isObject(value) || typeof value.id !== "string" || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,254}$/.test(value.id)) throw invalid("invalid_task_response", "Ark video returned an invalid task id"); return value.id; }
function statusBody(value: unknown): { status: "queued" | "running" | "cancelled" | "succeeded" | "failed"; content?: unknown; error?: unknown } {
  if (!isObject(value) || !["queued", "running", "cancelled", "succeeded", "failed"].includes(String(value.status))) throw invalid("invalid_status_response", "Ark video returned an invalid task status");
  return { status: value.status as "queued" | "running" | "cancelled" | "succeeded" | "failed", ...(value.content === undefined ? {} : { content: value.content }), ...(value.error === undefined ? {} : { error: value.error }) };
}
function videoUrl(value: unknown): string { if (!isObject(value) || typeof value.video_url !== "string") throw invalid("missing_video_output", "Ark video returned no output URL"); let url: URL; try { url = new URL(value.video_url); } catch { throw invalid("invalid_video_output", "Ark video returned an invalid output URL"); } if (url.protocol !== "https:") throw invalid("invalid_video_output", "Ark video output URL must use HTTPS"); return url.toString(); }
function responseDuration(value: unknown): number | undefined { if (!isObject(value)) return undefined; const duration = Number(value.duration); return Number.isFinite(duration) && duration > 0 && duration <= 300 ? duration : undefined; }
function failure(value: unknown, externalRequestId: string) { const error = isObject(value) ? value : {}; const code = typeof error.code === "string" ? error.code.slice(0, 128) : "provider_failed"; return { category: contentPolicyError(value) ? "content_policy" : "upstream", code: contentPolicyError(value) ? "content_policy_blocked" : code, message: contentPolicyError(value) ? "Video generation was blocked by provider safety policy" : "Video provider failed to generate the output", retryable: false, externalRequestId }; }
function contentPolicyError(value: unknown): boolean { const error = isObject(value) && isObject(value.error) ? value.error : isObject(value) ? value : {}; const code = typeof error.code === "string" ? error.code.toLowerCase() : ""; return code.includes("sensitive") || code.includes("contentpolicy") || code.includes("content_policy"); }
function enumValue<T extends string>(value: string | undefined, allowed: readonly T[], fallback: T, key: string): T { if (value === undefined) return fallback; if ((allowed as readonly string[]).includes(value)) return value as T; throw invalid(`invalid_${key}`, `Ark video ${key} configuration is invalid`); }
function invalid(code: string, message: string): ProviderError { return new ProviderError({ providerCode: "ark-video", category: "validation", code, message, retryable: false }); }
