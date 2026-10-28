import { randomInt } from "node:crypto";
import path from "node:path";
import sharp from "sharp";
import { assertRequestSupported } from "../providers/capabilities.ts";
import { ProviderError, normalizeProviderError } from "../providers/errors.ts";
import type { GenerationProvider } from "../providers/image-provider.ts";
import type { CostEstimate, GenerationRequest, JsonObject, JsonValue, MediaType, ProviderBinding, ProviderCallContext, ProviderCancelResult, ProviderDescriptor, ProviderHealthResult, ProviderImageOutput, ProviderOutput, ProviderStatusResult, ProviderSubmission, ProviderVideoOutput } from "../providers/types.ts";
import type { StorageProvider } from "../storage/storage-provider.ts";
import { injectPlaceholders, type PlaceholderValues } from "../workflows/placeholder-injector.ts";
import { WorkflowLoadError, type WorkflowLoader } from "../workflows/workflow-loader.ts";
import type { ComfyHistoryEntry, ComfyOutputRef, ComfyUIClient } from "./client.ts";

interface ComfyTaskContext {
  readonly mediaType: MediaType;
  readonly width: number;
  readonly height: number;
  readonly durationSeconds?: number;
}

export class ComfyUIProvider implements GenerationProvider {
  readonly descriptor: ProviderDescriptor = {
    code: "comfyui", displayName: "ComfyUI", availability: "active", priority: 10,
    capabilities: { mediaTypes: ["image", "video"], modes: ["text-to-image", "image-to-image", "text-to-video", "image-to-video"], workflowKinds: [], models: [], minWidth: 64, maxWidth: 8192, minHeight: 64, maxHeight: 8192, maxOutputs: 8, supportsSeed: true, supportsCancellation: true, supportsStatusPolling: true },
  };

  readonly #client: ComfyUIClient;
  readonly #workflows: WorkflowLoader;
  readonly #defaults: Readonly<JsonObject>;
  readonly #storage: StorageProvider | undefined;
  readonly #tasks = new Map<string, ComfyTaskContext>();
  constructor(client: ComfyUIClient, workflows: WorkflowLoader, defaults: Readonly<JsonObject> = {}, storage: StorageProvider | undefined = undefined) { this.#client = client; this.#workflows = workflows; this.#defaults = defaults; this.#storage = storage; }

  async generate(request: GenerationRequest, binding: ProviderBinding, context: ProviderCallContext): Promise<ProviderSubmission> {
    assertRequestSupported(this.descriptor, request);
    if (!binding.providerWorkflowRef) throw this.error("configuration", "workflow_ref_missing", "ComfyUI workflow reference is missing");
    const uploaded = await this.uploadReferenceImages(request, context);
    const refImages = uploaded.map((item) => item.name);
    const align = numeric(binding.providerConfig.align);
    const width = align ? alignToMultiple(request.width, align, 256) : request.width;
    const height = align ? alignToMultiple(request.height, align, 256) : request.height;
    try {
      const loaded = await this.#workflows.load(binding.providerWorkflowRef);
      const workflow = injectPlaceholders(loaded.template, this.values(request, binding, refImages, width, height)) as JsonObject;
      const externalRequestId = await this.#client.queuePrompt(workflow, context.attemptId, context.signal);
      const mediaType = request.mediaType ?? "image";
      this.#tasks.set(externalRequestId, {
        mediaType,
        width,
        height,
        ...(mediaType === "video" ? { durationSeconds: videoDuration(request, binding) } : {}),
      });
      return { externalRequestId, state: "queued", outputs: [], providerMetadata: { workflowName: loaded.workflowName, workflowVersion: loaded.workflowVersion, workflowDigest: loaded.digest, model: binding.providerModel ?? configuredValue(binding, this.#defaults, "model") ?? null } };
    } catch (error) { throw this.map(error); }
    finally { await this.cleanupReferenceImages(uploaded); }
  }

  async getStatus(externalRequestId: string, context: ProviderCallContext): Promise<ProviderStatusResult> {
    try {
      const task = this.#tasks.get(externalRequestId);
      if (!task) {
        // Worker-restart resilience: the in-memory task map is gone, but the
        // job may still be running upstream (ComfyUI history is authoritative).
        // Reconstruct a minimal task from the durable request metadata so we
        // keep polling instead of failing the job and refunding credits while
        // the upstream generation continues to run (and to cost money).
        if (context.taskMetadata?.mediaType === "video" || context.taskMetadata?.durationSeconds !== undefined) {
          const entry = await this.#client.getHistory(externalRequestId, context.signal).catch(() => undefined);
          if (!entry) return this.status(externalRequestId, "running", [], { phase: "recovering" }, 0.1);
          const refs = videoRefs(entry);
          if (refs.length === 0) return this.status(externalRequestId, "running", [], { phase: "waiting" }, 0.5);
          const meta = context.taskMetadata;
          const taskRecovered: ComfyTaskContext = {
            mediaType: "video" as const,
            width: meta?.width ?? 960,
            height: meta?.height ?? 544,
            ...(meta?.durationSeconds ? { durationSeconds: meta.durationSeconds } : {}),
          };
          const outputs: ProviderOutput[] = [];
          for (const [index, ref] of refs.entries()) {
            const extension = safeVideoExtension(ref);
            const filename = `${context.attemptId}-${index}${extension}`;
            const destination = safeChild(this.#client.config.downloadDirectory, filename);
            await this.#client.downloadOutput(ref, destination, context.signal);
            outputs.push({ mediaType: "video", kind: "local-file", path: destination, mimeType: videoMime(extension), width: taskRecovered.width, height: taskRecovered.height, durationSeconds: taskRecovered.durationSeconds ?? 1 } satisfies ProviderVideoOutput);
          }
          this.#tasks.set(externalRequestId, taskRecovered);
          return this.status(externalRequestId, "succeeded", outputs, { outputCount: outputs.length, recovered: true }, 1);
        }
        const entry = await this.#client.getHistory(externalRequestId, context.signal).catch(() => undefined);
        if (!entry) return this.status(externalRequestId, "running", [], { phase: "recovering" }, 0.1);
        const refs = imageRefs(entry);
        if (refs.length === 0) return this.status(externalRequestId, "running", [], { phase: "waiting" }, 0.5);
        const outputs: ProviderOutput[] = [];
        for (const [index, ref] of refs.entries()) {
          const extension = safeImageExtension(ref.filename);
          const filename = `${context.attemptId}-${index}${extension}`;
          const destination = safeChild(this.#client.config.downloadDirectory, filename);
          await this.#client.downloadOutput(ref, destination, context.signal);
          const metadata = await sharp(destination).metadata();
          const width = metadata.width;
          const height = metadata.height;
          if (!width || !height) throw this.error("validation", "invalid_image_dimensions", "ComfyUI output dimensions are invalid");
          outputs.push({ kind: "local-file", path: destination, mimeType: imageMime(extension), width, height } satisfies ProviderImageOutput);
        }
        const meta = context.taskMetadata;
        this.#tasks.set(externalRequestId, { mediaType: "image", width: meta?.width ?? outputs[0]?.width ?? 1024, height: meta?.height ?? outputs[0]?.height ?? 1024 });
        return this.status(externalRequestId, "succeeded", outputs, { outputCount: outputs.length, recovered: true }, 1);
      }
      const entry = await this.#client.getHistory(externalRequestId, context.signal);
      if (!entry) return this.status(externalRequestId, "running", [], { phase: "waiting" }, 0.1);
      if (failed(entry)) return { ...this.status(externalRequestId, "failed", [], { phase: "failed" }), error: { category: "upstream", code: "execution_failed", message: "ComfyUI execution failed", retryable: false, externalRequestId } };
      const refs = task.mediaType === "video" ? videoRefs(entry) : imageRefs(entry);
      if (!entry.status?.completed && refs.length === 0) return this.status(externalRequestId, "running", [], { phase: "executing" }, 0.5);
      if (refs.length === 0) return { ...this.status(externalRequestId, "failed", [], { phase: "empty" }), error: { category: "upstream", code: "no_output", message: `ComfyUI produced no ${task.mediaType} output`, retryable: false, externalRequestId } };
      const outputs: ProviderOutput[] = [];
      for (const [index, ref] of refs.entries()) {
        const extension = task.mediaType === "video" ? safeVideoExtension(ref) : safeImageExtension(ref.filename);
        const filename = `${context.attemptId}-${index}${extension}`;
        const destination = safeChild(this.#client.config.downloadDirectory, filename);
        await this.#client.downloadOutput(ref, destination, context.signal);
        if (task.mediaType === "video") {
          outputs.push({ mediaType: "video", kind: "local-file", path: destination, mimeType: videoMime(safeVideoExtension(ref)), width: task.width, height: task.height, durationSeconds: task.durationSeconds ?? 1 } satisfies ProviderVideoOutput);
          continue;
        }
        const metadata = await sharp(destination).metadata();
        const width = metadata.width;
        const height = metadata.height;
        if (!width || !height) throw this.error("validation", "invalid_image_dimensions", "ComfyUI output dimensions are invalid");
        outputs.push({ kind: "local-file", path: destination, mimeType: imageMime(extension), width, height } satisfies ProviderImageOutput);
      }
      this.#tasks.delete(externalRequestId);
      return this.status(externalRequestId, "succeeded", outputs, { outputCount: outputs.length }, 1);
    } catch (error) { throw this.map(error); }
  }

  async cancel(externalRequestId: string, context: ProviderCallContext): Promise<ProviderCancelResult> {
    try { const accepted = await this.#client.cancelPrompt(externalRequestId, context.signal); if (accepted) this.#tasks.delete(externalRequestId); return { externalRequestId, accepted, state: accepted ? "cancelled" : "failed" }; }
    catch (error) { throw this.map(error); }
  }

  async healthCheck(context: ProviderCallContext): Promise<ProviderHealthResult> {
    try { const latencyMs = await this.#client.healthCheck(context.signal); return { healthy: true, latencyMs, checkedAt: new Date() }; }
    catch { return { healthy: false, latencyMs: 0, checkedAt: new Date(), message: "ComfyUI health check failed" }; }
  }

  async estimateCost(_request: GenerationRequest, binding: ProviderBinding): Promise<CostEstimate> { return { amount: binding.estimatedCost ?? 0, currency: "USD", estimated: true }; }

  private values(request: GenerationRequest, binding: ProviderBinding, refImages: readonly string[] = [], width = request.width, height = request.height): PlaceholderValues {
    // Routing and execution controls are server-owned. In particular, never
    // allow a browser request to replace a catalog-selected model or LoRA.
    // The request seed remains user-selectable because it is a deliberate,
    // bounded generation input rather than a provider-routing control.
    const configured = (key: string, fallback?: JsonValue): JsonValue | undefined => binding.providerConfig[key] ?? this.#defaults[key] ?? fallback;
    const optionalValues = {
      seed: request.seed ?? configured("seed") ?? randomInt(0, 2_147_483_647),
      steps: configured("steps"),
      cfg: configured("cfg"),
      mu: configured("mu"),
      std: configured("std"),
      sampler: configured("sampler"),
      scheduler: configured("scheduler"),
      model: binding.providerModel ?? configured("model"),
      lora: configured("lora"),
      duration_seconds: request.mediaType === "video" ? videoDuration(request, binding) : undefined,
      frame_count: request.mediaType === "video" ? videoFrameCount(request, binding) : undefined,
      fps: request.mediaType === "video" ? videoFps(binding) : undefined,
    };
    return {
      prompt: request.prompt,
      negative_prompt: request.negativePrompt,
      width,
      height,
      ...(refImages[0] === undefined ? {} : { ref_image_0: refImages[0] }),
      ...(refImages[1] === undefined ? {} : { ref_image_1: refImages[1] }),
      ...(refImages[2] === undefined ? {} : { ref_image_2: refImages[2] }),
      ...Object.fromEntries(Object.entries(optionalValues).filter((entry): entry is [string, JsonValue] => entry[1] !== undefined)),
    };
  }

  private async uploadReferenceImages(request: GenerationRequest, context: ProviderCallContext): Promise<readonly { readonly name: string; readonly objectKey: string }[]> {
    const images = referenceImages(request);
    if (images.length === 0) return [];
    if (!this.#storage) throw this.error("configuration", "reference_storage_missing", "Reference image storage is not configured");
    const names: { name: string; objectKey: string }[] = [];
    for (const [index, image] of images.entries()) {
      const data = await this.#storage.download(image.objectKey);
      const uploaded = await this.#client.uploadImage(data, `${context.attemptId}-${index}${extensionForMime(image.mimeType)}`, context.signal);
      names.push({ name: uploaded.name, objectKey: image.objectKey });
    }
    return names;
  }

  private async cleanupReferenceImages(uploaded: readonly { readonly objectKey: string }[]): Promise<void> {
    if (!this.#storage) return;
    // Only delete the objects this request actually downloaded and uploaded to
    // ComfyUI. Never touch arbitrary keys derived from a caller-supplied
    // parameters.inputImages value — that would be a delete primitive for any
    // storage object whose key the caller can guess.
    await Promise.allSettled(uploaded.map((image) => this.#storage!.delete(image.objectKey)));
  }

  private status(externalRequestId: string, state: "running" | "succeeded" | "failed", outputs: readonly ProviderOutput[], providerMetadata: JsonObject, progress?: number): ProviderStatusResult { return { externalRequestId, state, outputs, providerMetadata, ...(progress === undefined ? {} : { progress }) }; }
  private map(error: unknown): ProviderError { if (error instanceof WorkflowLoadError) return this.error(error.code === "not_found" ? "configuration" : "validation", `workflow_${error.code}`, error.message); return normalizeProviderError(error, "comfyui"); }
  private error(category: "configuration" | "validation", code: string, message: string): ProviderError { return new ProviderError({ providerCode: "comfyui", category, code, message, retryable: false }); }
}

function referenceImages(request: GenerationRequest): readonly { readonly objectKey: string; readonly mimeType: string }[] {
  const raw = request.parameters.inputImages;
  if (raw === undefined) return [];
  if (!Array.isArray(raw)) throw new ProviderError({ providerCode: "comfyui", category: "validation", code: "invalid_reference_images", message: "Reference images are invalid", retryable: false });
  return raw.map((item) => {
    const value = item as { objectKey?: unknown; mimeType?: unknown };
    if (typeof value.objectKey !== "string" || typeof value.mimeType !== "string") throw new ProviderError({ providerCode: "comfyui", category: "validation", code: "invalid_reference_image", message: "Reference image metadata is invalid", retryable: false });
    // Ownership check: reference objects are only ever created by the
    // generation service under temp/inputs/{userId}/{requestId}/ (see
    // GenerationService.persistInputImages). Refusing any other key prevents
    // a caller-controlled parameters.inputImages from reading or deleting
    // arbitrary storage objects even if an older job row was already written.
    if (!value.objectKey.startsWith("temp/inputs/")) throw new ProviderError({ providerCode: "comfyui", category: "validation", code: "unsafe_reference_image", message: "Reference image object key is not server-owned", retryable: false });
    return { objectKey: value.objectKey, mimeType: value.mimeType };
  });
}
function extensionForMime(mimeType: string): string {
  if (mimeType === "image/jpeg") return ".jpg";
  if (mimeType === "image/webp") return ".webp";
  if (mimeType === "image/png") return ".png";
  throw new ProviderError({ providerCode: "comfyui", category: "validation", code: "unsupported_reference_image", message: "Reference image format is unsupported", retryable: false });
}
function alignToMultiple(value: number, multiple: number, minimum: number): number {
  const aligned = Math.round(value / multiple) * multiple;
  return Math.max(minimum, Math.min(16_384, aligned));
}

function failed(entry: ComfyHistoryEntry): boolean { return entry.status?.status_str === "error" || Boolean(entry.status?.messages?.some((value) => Array.isArray(value) && value[0] === "execution_error")); }
function imageRefs(entry: ComfyHistoryEntry): ComfyOutputRef[] { return Object.values(entry.outputs ?? {}).flatMap((output) => output.images ?? []).filter((item) => item.type === "output"); }
function videoRefs(entry: ComfyHistoryEntry): ComfyOutputRef[] {
  return Object.values(entry.outputs ?? {})
    .flatMap((output) => [...(output.videos ?? []), ...(output.gifs ?? [])])
    .filter((item) => item.type === "output" && isVideoRef(item));
}
function isVideoRef(ref: ComfyOutputRef): boolean { return new Set([".mp4", ".webm", ".mov"]).has(path.extname(ref.filename).toLowerCase()) || ref.format?.startsWith("video/") === true; }
function safeImageExtension(filename: string): string { const ext = path.extname(filename).toLowerCase(); return new Set([".png", ".jpg", ".jpeg", ".webp"]).has(ext) ? ext : ".png"; }
function safeVideoExtension(ref: ComfyOutputRef): ".mp4" | ".webm" | ".mov" { const ext = path.extname(ref.filename).toLowerCase(); if (ext === ".webm" || ext === ".mov") return ext; if (ext === ".mp4" || ref.format?.includes("mp4")) return ".mp4"; throw new ProviderError({ providerCode: "comfyui", category: "validation", code: "unsupported_video_output", message: "ComfyUI video output format is unsupported", retryable: false }); }
function imageMime(extension: string): string { return extension === ".jpg" || extension === ".jpeg" ? "image/jpeg" : extension === ".webp" ? "image/webp" : "image/png"; }
function videoMime(extension: ".mp4" | ".webm" | ".mov"): "video/mp4" | "video/webm" | "video/quicktime" { return extension === ".webm" ? "video/webm" : extension === ".mov" ? "video/quicktime" : "video/mp4"; }
function videoDuration(request: GenerationRequest, binding: ProviderBinding): number { const value = numeric(request.parameters.durationSeconds) ?? numeric(binding.providerConfig.durationSeconds) ?? 5; if (!Number.isSafeInteger(value) || value < 1 || value > 300) throw new ProviderError({ providerCode: "comfyui", category: "validation", code: "invalid_video_duration", message: "ComfyUI video duration is invalid", retryable: false }); return value; }
function videoFps(binding: ProviderBinding): number { const value = numeric(binding.providerConfig.fps) ?? 24; if (!Number.isSafeInteger(value) || value < 1 || value > 120) throw new ProviderError({ providerCode: "comfyui", category: "configuration", code: "invalid_video_fps", message: "ComfyUI video FPS is invalid", retryable: false }); return value; }
function videoFrameCount(request: GenerationRequest, binding: ProviderBinding): number { const configured = numeric(binding.providerConfig.frameCount); const value = configured ?? videoDuration(request, binding) * videoFps(binding) + 1; if (!Number.isSafeInteger(value) || value < 2 || value > 36_001) throw new ProviderError({ providerCode: "comfyui", category: "configuration", code: "invalid_video_frame_count", message: "ComfyUI video frame count is invalid", retryable: false }); return value; }
function numeric(value: JsonValue | undefined): number | undefined { return typeof value === "number" && Number.isFinite(value) ? value : undefined; }
function configuredValue(binding: ProviderBinding, defaults: Readonly<JsonObject>, key: string): JsonValue | undefined { return binding.providerConfig[key] ?? defaults[key]; }
function safeChild(root: string, name: string): string { const resolvedRoot = path.resolve(root); const result = path.resolve(resolvedRoot, name); if (path.dirname(result) !== resolvedRoot) throw new ProviderError({ providerCode: "comfyui", category: "validation", code: "unsafe_output_path", message: "ComfyUI output path is invalid" }); return result; }
