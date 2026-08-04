import type { ViewerContext } from "../gallery/types.ts";
import type { JsonObject } from "../providers/types.ts";
import { GenerationError } from "./errors.ts";
import type { GenerationRepository } from "./repository.ts";
import type { GenerationView, GenerationVisibility, PromptVisibility } from "./types.ts";

export interface GenerationCancellationPort {
  requestCancellation(jobId: string, reason?: string): Promise<unknown>;
}

export class GenerationService {
  readonly #repository: GenerationRepository;
  readonly #defaultCreditCost: string;
  readonly #cancellation: GenerationCancellationPort | undefined;
  readonly #ready: boolean;

  constructor(options: { readonly repository: GenerationRepository; readonly defaultCreditCost?: string; readonly cancellation?: GenerationCancellationPort; readonly ready?: boolean }) {
    this.#repository = options.repository;
    this.#defaultCreditCost = creditAmount(options.defaultCreditCost ?? "1.0000");
    this.#cancellation = options.cancellation;
    this.#ready = options.ready ?? true;
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
    const key = token(idempotencyKey, "Idempotency-Key", 128);
    return this.#repository.create({ userId, requestId: viewer.requestId, idempotencyKey: key, workflowSlug, prompt, negativePrompt, width, height, count, visibility, promptVisibility, parameters }, this.#defaultCreditCost);
  }

  async get(id: string, viewer: ViewerContext): Promise<GenerationView> {
    const userId = requireUser(viewer);
    const generation = await this.#repository.findForViewer(identifier(id), userId, viewer.role === "admin");
    if (!generation) throw new GenerationError("generation_not_found", "未找到该创作任务。", 404);
    return generation;
  }

  async cancel(id: string, viewer: ViewerContext): Promise<{ readonly generation: GenerationView; readonly accepted: boolean }> {
    const userId = requireUser(viewer);
    const result = await this.#repository.requestCancellation(identifier(id), userId, viewer.role === "admin");
    if (!result) throw new GenerationError("generation_not_found", "未找到该创作任务。", 404);
    if (result.signalWorker && this.#cancellation) await this.#cancellation.requestCancellation(result.generation.id, "user_requested").catch(() => undefined);
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
  const allowed = new Set(["workflowSlug", "prompt", "negativePrompt", "width", "height", "count", "visibility", "promptVisibility", "parameters"]);
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
