import { GalleryCursorCodec, type DecodedCursor } from "../gallery/cursor.ts";
import type { ViewerContext } from "../gallery/types.ts";
import type { JsonObject } from "../providers/types.ts";
import { GenerationError } from "./errors.ts";
import type { GenerationRepository } from "./repository.ts";
import type { GenerationListRequest, GenerationPage, GenerationStatus, GenerationView, GenerationVisibility, PromptVisibility } from "./types.ts";

export interface GenerationCancellationPort {
  requestCancellation(jobId: string, reason?: string): Promise<{ readonly mode: "removed" | "signalled" | "terminal" | "missing" } | undefined>;
}

export class GenerationService {
  readonly #repository: GenerationRepository;
  readonly #defaultCreditCost: string;
  readonly #cancellation: GenerationCancellationPort | undefined;
  readonly #ready: boolean;
  readonly #cursor: GalleryCursorCodec | undefined;

  constructor(options: { readonly repository: GenerationRepository; readonly defaultCreditCost?: string; readonly cancellation?: GenerationCancellationPort; readonly ready?: boolean; readonly cursor?: GalleryCursorCodec }) {
    this.#repository = options.repository;
    this.#defaultCreditCost = creditAmount(options.defaultCreditCost ?? "1.0000");
    this.#cancellation = options.cancellation;
    this.#ready = options.ready ?? true;
    this.#cursor = options.cursor;
  }

  listWorkflows() { return this.#repository.listWorkflows(this.#defaultCreditCost); }

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
    return this.#repository.create({ userId, requestId: viewer.requestId, idempotencyKey: key, workflowSlug, prompt, negativePrompt, width, height, count, visibility, promptVisibility, parameters, creditTier }, this.#defaultCreditCost);
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
    // When the queue has no live job left (worker restart, stall, retention or
    // an already terminal BullMQ job), nobody will finalize the cancellation,
    // so the database state must be flipped here; otherwise the task would
    // stay "running" forever and the UI would keep polling.
    if (result.signalWorker && receipt && (receipt.mode === "terminal" || receipt.mode === "missing")) {
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
  const allowed = new Set(["workflowSlug", "prompt", "negativePrompt", "width", "height", "count", "visibility", "promptVisibility", "parameters", "creditTier"]);
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

export type { GenerationVisibility, PromptVisibility };
