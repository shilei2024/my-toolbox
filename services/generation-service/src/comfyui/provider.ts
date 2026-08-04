import path from "node:path";
import { imageSizeFromFile } from "image-size/fromFile";
import { assertRequestSupported } from "../providers/capabilities.ts";
import { ProviderError, normalizeProviderError } from "../providers/errors.ts";
import type { ImageProvider } from "../providers/image-provider.ts";
import type { CostEstimate, GenerationRequest, JsonObject, JsonValue, ProviderBinding, ProviderCallContext, ProviderCancelResult, ProviderDescriptor, ProviderHealthResult, ProviderImageOutput, ProviderStatusResult, ProviderSubmission } from "../providers/types.ts";
import { injectPlaceholders, type PlaceholderValues } from "../workflows/placeholder-injector.ts";
import { WorkflowLoadError, type WorkflowLoader } from "../workflows/workflow-loader.ts";
import type { ComfyHistoryEntry, ComfyImageRef, ComfyUIClient } from "./client.ts";

export class ComfyUIProvider implements ImageProvider {
  readonly descriptor: ProviderDescriptor = {
    code: "comfyui", displayName: "ComfyUI", availability: "active", priority: 10,
    capabilities: { modes: ["text-to-image", "image-to-image"], workflowKinds: [], models: [], minWidth: 64, maxWidth: 8192, minHeight: 64, maxHeight: 8192, maxOutputs: 8, supportsSeed: true, supportsCancellation: true, supportsStatusPolling: true },
  };

  readonly #client: ComfyUIClient;
  readonly #workflows: WorkflowLoader;
  readonly #defaults: Readonly<JsonObject>;
  constructor(client: ComfyUIClient, workflows: WorkflowLoader, defaults: Readonly<JsonObject> = {}) { this.#client = client; this.#workflows = workflows; this.#defaults = defaults; }

  async generate(request: GenerationRequest, binding: ProviderBinding, context: ProviderCallContext): Promise<ProviderSubmission> {
    assertRequestSupported(this.descriptor, request);
    if (!binding.providerWorkflowRef) throw this.error("configuration", "workflow_ref_missing", "ComfyUI workflow reference is missing");
    try {
      const loaded = await this.#workflows.load(binding.providerWorkflowRef);
      const workflow = injectPlaceholders(loaded.template, this.values(request, binding)) as JsonObject;
      const externalRequestId = await this.#client.queuePrompt(workflow, context.attemptId, context.signal);
      return { externalRequestId, state: "queued", outputs: [], providerMetadata: { workflowName: loaded.workflowName, workflowVersion: loaded.workflowVersion, workflowDigest: loaded.digest, model: binding.providerModel ?? null } };
    } catch (error) { throw this.map(error); }
  }

  async getStatus(externalRequestId: string, context: ProviderCallContext): Promise<ProviderStatusResult> {
    try {
      const entry = await this.#client.getHistory(externalRequestId, context.signal);
      if (!entry) return this.status(externalRequestId, "running", [], { phase: "waiting" }, 0.1);
      if (failed(entry)) return { ...this.status(externalRequestId, "failed", [], { phase: "failed" }), error: { category: "upstream", code: "execution_failed", message: "ComfyUI execution failed", retryable: false, externalRequestId } };
      const refs = imageRefs(entry);
      if (!entry.status?.completed && refs.length === 0) return this.status(externalRequestId, "running", [], { phase: "executing" }, 0.5);
      if (refs.length === 0) return { ...this.status(externalRequestId, "failed", [], { phase: "empty" }), error: { category: "upstream", code: "no_output", message: "ComfyUI produced no image output", retryable: false, externalRequestId } };
      const outputs: ProviderImageOutput[] = [];
      for (const [index, ref] of refs.entries()) {
        const extension = safeExtension(ref.filename);
        const filename = `${context.attemptId}-${index}${extension}`;
        const destination = safeChild(this.#client.config.downloadDirectory, filename);
        await this.#client.downloadImage(ref, destination, context.signal);
        const dimensions = await imageSizeFromFile(destination);
        if (!dimensions.width || !dimensions.height) throw this.error("validation", "invalid_image_dimensions", "ComfyUI output dimensions are invalid");
        outputs.push({ kind: "local-file", path: destination, mimeType: mime(extension), width: dimensions.width, height: dimensions.height });
      }
      return this.status(externalRequestId, "succeeded", outputs, { outputCount: outputs.length }, 1);
    } catch (error) { throw this.map(error); }
  }

  async cancel(externalRequestId: string, context: ProviderCallContext): Promise<ProviderCancelResult> {
    try { const accepted = await this.#client.cancelPrompt(externalRequestId, context.signal); return { externalRequestId, accepted, state: accepted ? "cancelled" : "failed" }; }
    catch (error) { throw this.map(error); }
  }

  async healthCheck(context: ProviderCallContext): Promise<ProviderHealthResult> {
    try { const latencyMs = await this.#client.healthCheck(context.signal); return { healthy: true, latencyMs, checkedAt: new Date() }; }
    catch { return { healthy: false, latencyMs: 0, checkedAt: new Date(), message: "ComfyUI health check failed" }; }
  }

  async estimateCost(_request: GenerationRequest, binding: ProviderBinding): Promise<CostEstimate> { return { amount: binding.estimatedCost ?? 0, currency: "USD", estimated: true }; }

  private values(request: GenerationRequest, binding: ProviderBinding): PlaceholderValues {
    const parameter = (key: string, fallback?: JsonValue): JsonValue | undefined => request.parameters[key] ?? binding.providerConfig[key] ?? this.#defaults[key] ?? fallback;
    const optionalValues = {
      seed: request.seed,
      steps: parameter("steps"),
      cfg: parameter("cfg"),
      sampler: parameter("sampler"),
      scheduler: parameter("scheduler"),
      model: binding.providerModel ?? parameter("model"),
      lora: parameter("lora"),
    };
    return {
      prompt: request.prompt,
      negative_prompt: request.negativePrompt,
      width: request.width,
      height: request.height,
      ...Object.fromEntries(Object.entries(optionalValues).filter((entry): entry is [string, JsonValue] => entry[1] !== undefined)),
    };
  }

  private status(externalRequestId: string, state: "running" | "succeeded" | "failed", outputs: readonly ProviderImageOutput[], providerMetadata: JsonObject, progress?: number): ProviderStatusResult { return { externalRequestId, state, outputs, providerMetadata, ...(progress === undefined ? {} : { progress }) }; }
  private map(error: unknown): ProviderError { if (error instanceof WorkflowLoadError) return this.error(error.code === "not_found" ? "configuration" : "validation", `workflow_${error.code}`, error.message); return normalizeProviderError(error, "comfyui"); }
  private error(category: "configuration" | "validation", code: string, message: string): ProviderError { return new ProviderError({ providerCode: "comfyui", category, code, message, retryable: false }); }
}

function failed(entry: ComfyHistoryEntry): boolean { return entry.status?.status_str === "error" || Boolean(entry.status?.messages?.some((value) => Array.isArray(value) && value[0] === "execution_error")); }
function imageRefs(entry: ComfyHistoryEntry): ComfyImageRef[] { return Object.values(entry.outputs ?? {}).flatMap((output) => output.images ?? []).filter((item) => item.type === "output"); }
function safeExtension(filename: string): string { const ext = path.extname(filename).toLowerCase(); return new Set([".png", ".jpg", ".jpeg", ".webp"]).has(ext) ? ext : ".png"; }
function mime(extension: string): string { return extension === ".jpg" || extension === ".jpeg" ? "image/jpeg" : extension === ".webp" ? "image/webp" : "image/png"; }
function safeChild(root: string, name: string): string { const resolvedRoot = path.resolve(root); const result = path.resolve(resolvedRoot, name); if (path.dirname(result) !== resolvedRoot) throw new ProviderError({ providerCode: "comfyui", category: "validation", code: "unsafe_output_path", message: "ComfyUI output path is invalid" }); return result; }
