import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import { GalleryError } from "../gallery/errors.ts";
import type { ViewerContext } from "../gallery/types.ts";
import type { AdminRepository } from "./repository.ts";
import type { AdminDashboard, AdminImageItem, AdminProviderItem, AdminProviderModelItem, AdminWorkflowItem, ModerateImageCommand, UpdateProviderCommand, UpdateProviderModelCommand, UpdateWorkflowCommand } from "./types.ts";

export class AdminService {
  readonly #repository: AdminRepository;
  readonly #logger: StructuredLogger;
  readonly #onContentChanged: () => Promise<void>;

  constructor(options: { repository: AdminRepository; logger: StructuredLogger; onContentChanged: () => Promise<void> }) {
    this.#repository = options.repository;
    this.#logger = options.logger;
    this.#onContentChanged = options.onContentChanged;
  }

  async dashboard(viewer: ViewerContext): Promise<AdminDashboard> {
    requireAdmin(viewer);
    return this.#repository.dashboard();
  }

  async moderateImage(imageId: string, input: unknown, viewer: ViewerContext): Promise<AdminImageItem> {
    const adminUserId = requireAdmin(viewer);
    const command = parseModeration(input);
    const result = await this.#repository.moderateImage(uuid(imageId), command, adminUserId, viewer.requestId);
    await this.#onContentChanged();
    this.#logger.info("admin.image_moderated", { requestId: viewer.requestId, actorUserId: adminUserId, imageId, decision: command.decision });
    return result;
  }

  async updateProvider(providerId: string, input: unknown, viewer: ViewerContext): Promise<AdminProviderItem> {
    const adminUserId = requireAdmin(viewer);
    const command = parseProvider(input);
    const result = await this.#repository.updateProvider(uuid(providerId), command, adminUserId, viewer.requestId);
    this.#logger.info("admin.provider_updated", { requestId: viewer.requestId, actorUserId: adminUserId, providerId, status: command.status, priority: command.priority });
    return result;
  }

  async updateProviderModel(modelId: string, input: unknown, viewer: ViewerContext): Promise<AdminProviderModelItem> {
    const adminUserId = requireAdmin(viewer);
    const command = parseProviderModel(input);
    const result = await this.#repository.updateProviderModel(uuid(modelId), command, adminUserId, viewer.requestId);
    this.#logger.info("admin.provider_model_updated", { requestId: viewer.requestId, actorUserId: adminUserId, modelId, tier: command.tier, isEnabled: command.isEnabled });
    return result;
  }

  async updateWorkflow(workflowId: string, input: unknown, viewer: ViewerContext): Promise<AdminWorkflowItem> {
    const adminUserId = requireAdmin(viewer);
    const command = parseWorkflow(input);
    const result = await this.#repository.updateWorkflow(uuid(workflowId), command, adminUserId, viewer.requestId);
    this.#logger.info("admin.workflow_updated", { requestId: viewer.requestId, actorUserId: adminUserId, workflowId, isEnabled: command.isEnabled, sortOrder: command.sortOrder });
    return result;
  }
}

function requireAdmin(viewer: ViewerContext): number {
  if (viewer.role === "guest") throw new GalleryError("authentication_required", "Authentication is required", 401);
  if (viewer.role !== "admin" || !Number.isInteger(viewer.userId) || (viewer.userId ?? 0) <= 0) throw new GalleryError("forbidden", "Administrator permission is required", 403);
  return viewer.userId as number;
}

function parseModeration(value: unknown): ModerateImageCommand {
  const body = object(value, ["decision", "reasonCodes", "expectedUpdatedAt"]);
  const decision = body.decision;
  if (decision !== "approved" && decision !== "rejected") throw invalid("decision is invalid");
  const reasonCodes = body.reasonCodes;
  if (!Array.isArray(reasonCodes) || reasonCodes.length > 20 || reasonCodes.some((item) => typeof item !== "string" || !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(item))) throw invalid("reasonCodes is invalid");
  return { decision, reasonCodes: reasonCodes as string[], expectedUpdatedAt: timestamp(body.expectedUpdatedAt) };
}

function parseProvider(value: unknown): UpdateProviderCommand {
  const body = object(value, ["status", "priority", "expectedUpdatedAt"]);
  if (body.status !== "active" && body.status !== "disabled") throw invalid("status is invalid");
  return { status: body.status, priority: integer(body.priority, 0, 10_000, "priority"), expectedUpdatedAt: timestamp(body.expectedUpdatedAt) };
}

function parseProviderModel(value: unknown): UpdateProviderModelCommand {
  const body = object(value, ["tier", "creditCost", "isDefault", "isEnabled", "expectedUpdatedAt"]);
  if (body.tier !== "free" && body.tier !== "member") throw invalid("tier is invalid");
  if (typeof body.isDefault !== "boolean" || typeof body.isEnabled !== "boolean") throw invalid("isDefault/isEnabled is invalid");
  let creditCost: number | undefined;
  if (body.creditCost !== undefined && body.creditCost !== null) {
    if (typeof body.creditCost !== "number" || !Number.isFinite(body.creditCost) || body.creditCost < 0 || body.creditCost > 1_000_000) throw invalid("creditCost is invalid");
    creditCost = Math.round(body.creditCost * 10_000) / 10_000;
  }
  return { tier: body.tier, ...(creditCost === undefined ? {} : { creditCost }), isDefault: body.isDefault, isEnabled: body.isEnabled, expectedUpdatedAt: timestamp(body.expectedUpdatedAt) };
}

function parseWorkflow(value: unknown): UpdateWorkflowCommand {
  const body = object(value, ["isEnabled", "sortOrder", "expectedUpdatedAt"]);
  if (typeof body.isEnabled !== "boolean") throw invalid("isEnabled is invalid");
  return { isEnabled: body.isEnabled, sortOrder: integer(body.sortOrder, 0, 10_000, "sortOrder"), expectedUpdatedAt: timestamp(body.expectedUpdatedAt) };
}

function object(value: unknown, allowed: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid("request body is invalid");
  const result = value as Record<string, unknown>;
  if (Object.keys(result).some((key) => !allowed.includes(key))) throw invalid("request body contains unsupported fields");
  return result;
}

function uuid(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f-]{27}$/.test(normalized)) throw invalid("resource id is invalid");
  return normalized;
}

function timestamp(value: unknown): string {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) throw invalid("expectedUpdatedAt is invalid");
  return new Date(value).toISOString();
}

function integer(value: unknown, min: number, max: number, field: string): number {
  if (!Number.isInteger(value) || Number(value) < min || Number(value) > max) throw invalid(`${field} is invalid`);
  return Number(value);
}

function invalid(message: string): GalleryError { return new GalleryError("invalid_request", message, 400); }
