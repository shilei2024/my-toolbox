import { createHash } from "node:crypto";
import { GalleryCursorCodec, type DecodedCursor } from "../gallery/cursor.ts";
import type { ViewerContext } from "../gallery/types.ts";
import type { JsonObject } from "../providers/types.ts";
import type { StorageProvider } from "../storage/storage-provider.ts";
import type { MediaType } from "../providers/types.ts";
import { GenerationError } from "./errors.ts";
import type { GenerationRepository } from "./repository.ts";
import type { GenerationListRequest, GenerationMode, GenerationPage, GenerationStatus, GenerationView, GenerationVisibility, PromptVisibility } from "./types.ts";

export interface GenerationCancellationPort {
  requestCancellation(jobId: string, reason?: string): Promise<{ readonly mode: "removed" | "signalled" | "terminal" | "missing" } | undefined>;
}

export class GenerationService {
  readonly #repository: GenerationRepository;
  readonly #defaultCreditCost: string;
  readonly #cancellation: GenerationCancellationPort | undefined;
  readonly #ready: boolean;
  readonly #cursor: GalleryCursorCodec | undefined;
  readonly #storage: StorageProvider | undefined;

  constructor(options: { readonly repository: GenerationRepository; readonly defaultCreditCost?: string; readonly cancellation?: GenerationCancellationPort; readonly ready?: boolean; readonly cursor?: GalleryCursorCodec; readonly storage?: StorageProvider }) {
    this.#repository = options.repository;
    this.#defaultCreditCost = creditAmount(options.defaultCreditCost ?? "1.0000");
    this.#cancellation = options.cancellation;
    this.#ready = options.ready ?? true;
    this.#cursor = options.cursor;
    this.#storage = options.storage;
  }

  listWorkflows(mode?: GenerationMode, mediaType?: MediaType) { return this.#repository.listWorkflows(this.#defaultCreditCost, mode, mediaType); }

  async create(body: unknown, idempotencyKey: string | undefined, viewer: ViewerContext): Promise<GenerationView> {
    if (!this.#ready) {
      throw new GenerationError("generation_queue_not_configured", "创作服务正在维护中，请稍后再试。", 503);
    }
    const userId = requireUser(viewer);
    const input = record(body);
    const workflowSlug = token(input.workflowSlug, "workflowSlug", 128);
    const prompt = text(input.prompt, "prompt", 1, 8000);
    const negativePrompt = optionalText(input.negativePrompt, "negativePrompt", 8000);
    const width = integer(input.width, "width", 64, 8192);
    const height = integer(input.height, "height", 64, 8192);
    const count = integer(input.count, "count", 1, 8);
    const visibility = enumValue(input.visibility, "visibility", ["public", "private"] as const);
    const promptVisibility = enumValue(input.promptVisibility, "promptVisibility", ["public", "hidden"] as const);
    const parameters = jsonObject(input.parameters ?? {}, "parameters");
    const creditTier = input.creditTier === undefined ? "free" : enumValue(input.creditTier, "creditTier", ["free", "member"] as const);
    const key = token(idempotencyKey, "Idempotency-Key", 128);
    const inputImages = await this.persistInputImages(input.inputImages, userId, viewer.requestId);
    try {
      return await this.#repository.create({ userId, requestId: viewer.requestId, idempotencyKey: key, workflowSlug, prompt, negativePrompt, width, height, count, visibility, promptVisibility, parameters: inputImages.length ? { ...parameters, inputImages } : parameters, creditTier }, this.#defaultCreditCost);
    } catch (error) {
      await Promise.allSettled(inputImages.map((image) => this.#storage?.delete(image.objectKey)));
      throw error;
    }
  }

  private async persistInputImages(value: unknown, userId: number, requestId: string): Promise<{ objectKey: string; name: string; sha256: string; byteSize: number; mimeType: string }[]> {
    if (value === undefined) return [];
    if (!Array.isArray(value) || value.length > 3) throw new GenerationError("invalid_request", "inputImages 最多 3 张。", 400);
    if (!this.#storage) throw new GenerationError("invalid_request", "参考图存储未配置。", 503);
    const images: { objectKey: string; name: string; sha256: string; byteSize: number; mimeType: string }[] = [];
    try {
      for (const [index, item] of value.entries()) {
        const raw = item as { name?: unknown; data?: unknown };
        const name = typeof raw.name === "string" ? raw.name.trim() : "";
        const data = typeof raw.data === "string" ? raw.data : "";
        if (!name || name.length > 128 || !data) throw new GenerationError("invalid_request", "参考图格式不正确。", 400);
        const decoded = decodeDataUrl(data);
        if (!decoded) throw new GenerationError("invalid_request", "参考图必须是 PNG/JPEG/WebP 的 data URL。", 400);
        if (decoded.data.length > MAX_REFERENCE_IMAGE_BYTES) throw new GenerationError("invalid_request", "单张参考图不能超过 3MB。", 400);
        const objectKey = `temp/inputs/${userId}/${requestId}/${index}${extensionForMime(decoded.mimeType)}`;
        await this.#storage.upload({ objectKey, body: decoded.data, contentType: decoded.mimeType, contentLength: decoded.data.length });
        images.push({ objectKey, name, sha256: createHash("sha256").update(decoded.data).digest("hex"), byteSize: decoded.data.length, mimeType: decoded.mimeType });
      }
      return images;
    } catch (error) {
      await Promise.allSettled(images.map((image) => this.#storage?.delete(image.objectKey)));
      throw error;
    }
  }

  async get(id: string, viewer: ViewerContext): Promise<GenerationView> {
    const userId = requireUser(viewer);
    const generation = await this.#repository.findForViewer(identifier(id), userId, viewer.role === "admin");
    if (!generation) throw new GenerationError("generation_not_found", "未找到该创作任务。", 404);
    return generation;
  }

  async list(query: GenerationListRequest, viewer: ViewerContext): Promise<GenerationPage> {
    const userId = requireUser(viewer);
    const limit = boundedLimit(query.limit);
    const status = query.status === undefined ? undefined : statusValue(query.status);
    const scope = `generations:${userId}`;
    const cursor = this.#cursor ? decodeCursor(this.#cursor, scope, query.cursor) : undefined;
    const page = await this.#repository.listForViewer(userId, cursor, limit, status);
    return { items: page.items, ...(page.next && this.#cursor ? { nextCursor: this.#cursor.encode(scope, page.next) } : {}) };
  }

  async cancel(id: string, viewer: ViewerContext): Promise<{ readonly generation: GenerationView; readonly accepted: boolean }> {
    const userId = requireUser(viewer);
    const result = await this.#repository.requestCancellation(identifier(id), userId, viewer.role === "admin");
    if (!result) throw new GenerationError("generation_not_found", "未找到该创作任务。", 404);
    const receipt = result.signalWorker && this.#cancellation
      ? await this.#cancellation.requestCancellation(result.generation.id, "user_requested").catch(() => undefined)
      : undefined;
    // A removed BullMQ job has no worker left to settle the database row. The
    // same is true for missing/terminal jobs and for deployments without a
    // queue cancellation adapter. Finalize all of these paths here so the
    // credit reservation cannot remain active indefinitely.
    if (result.signalWorker && (!receipt || receipt.mode === "removed" || receipt.mode === "terminal" || receipt.mode === "missing")) {
      const finalized = await this.#repository.finalizeCancellation(result.generation.id, userId, viewer.role === "admin");
      if (finalized) return { generation: finalized, accepted: true };
    }
    return { generation: result.generation, accepted: result.accepted };
  }
}

function requireUser(viewer: ViewerContext): number {
  if (!viewer.userId || viewer.role === "guest") throw new GenerationError("authentication_required", "请先登录后再开始创作。", 401);
  return viewer.userId;
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new GenerationError("invalid_request", "请求内容格式不正确。", 400);
  const result = value as Record<string, unknown>;
  const allowed = new Set(["workflowSlug", "prompt", "negativePrompt", "width", "height", "count", "visibility", "promptVisibility", "parameters", "creditTier", "inputImages"]);
  if (Object.keys(result).some((key) => !allowed.has(key))) throw new GenerationError("invalid_request", "请求包含不支持的字段。", 400);
  return result;
}
function text(value: unknown, field: string, min: number, max: number): string {
  if (typeof value !== "string" || value.trim().length < min || value.length > max) throw new GenerationError("invalid_request", `${field} 格式不正确。`, 400);
  return value.trim();
}
function optionalText(value: unknown, field: string, max: number): string { return value === undefined ? "" : text(value, field, 0, max); }
function token(value: unknown, field: string, max: number): string {
  if (typeof value !== "string" || value.length > max || !/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(value)) throw new GenerationError("invalid_request", `${field} 格式不正确。`, 400);
  return value;
}
function identifier(value: string): string { return token(value, "generationId", 128); }
function boundedLimit(value: number | undefined): number {
  if (value === undefined) return 24;
  if (!Number.isSafeInteger(value) || value < 1 || value > 50) throw new GenerationError("invalid_request", "limit 必须是 1 到 50 之间的整数。", 400);
  return value;
}
function statusValue(value: GenerationStatus): GenerationStatus {
  if (!new Set<GenerationStatus>(["pending", "running", "completed", "failed", "cancelled"]).has(value)) throw new GenerationError("invalid_request", "status 格式不正确。", 400);
  return value;
}
function decodeCursor(codec: GalleryCursorCodec, scope: string, token: string | undefined): DecodedCursor | undefined {
  if (token === undefined) return undefined;
  try {
    return codec.decode(scope, token);
  } catch {
    throw new GenerationError("invalid_cursor", "分页游标无效，请刷新后重试。", 400);
  }
}
function integer(value: unknown, field: string, min: number, max: number): number {
  if (!Number.isSafeInteger(value) || Number(value) < min || Number(value) > max) throw new GenerationError("invalid_request", `${field} 超出允许范围。`, 400);
  return Number(value);
}
function enumValue<T extends string>(value: unknown, field: string, allowed: readonly T[]): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) throw new GenerationError("invalid_request", `${field} 格式不正确。`, 400);
  return value as T;
}
function jsonObject(value: unknown, field: string): Readonly<JsonObject> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new GenerationError("invalid_request", `${field} 格式不正确。`, 400);
  const encoded = JSON.stringify(value);
  if (encoded.length > 8192) throw new GenerationError("invalid_request", `${field} 内容过大。`, 400);
  return value as JsonObject;
}
function creditAmount(value: string): string {
  if (!/^(?:0|[1-9]\d{0,8})(?:\.\d{1,4})?$/.test(value) || Number(value) < 0) throw new Error("GENERATION_DEFAULT_CREDIT_COST is invalid");
  return Number(value).toFixed(4);
}

const MAX_REFERENCE_IMAGE_BYTES = 3 * 1024 * 1024;
function decodeDataUrl(value: string): { readonly mimeType: "image/png" | "image/jpeg" | "image/webp"; readonly data: Buffer } | undefined {
  const match = /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$/.exec(value.trim());
  if (!match) return undefined;
  const mimeType = match[1] as "image/png" | "image/jpeg" | "image/webp";
  return { mimeType, data: Buffer.from(match[2]!, "base64") };
}
function extensionForMime(mimeType: "image/png" | "image/jpeg" | "image/webp"): string {
  if (mimeType === "image/jpeg") return ".jpg";
  if (mimeType === "image/webp") return ".webp";
  return ".png";
}

export type { GenerationVisibility, PromptVisibility };
