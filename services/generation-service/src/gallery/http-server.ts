import rateLimit from "@fastify/rate-limit";
import Fastify, { type FastifyInstance, type FastifyRequest } from "fastify";
import type { Redis } from "ioredis";
import type { AdminService } from "../admin/admin-service.ts";
import type { BillingService } from "../billing/billing-service.ts";
import { BillingError } from "../billing/errors.ts";
import type { GenerationService } from "../generation/generation-service.ts";
import { GenerationError, normalizeGenerationError } from "../generation/errors.ts";
import type { GenerationListRequest, GenerationStatus } from "../generation/types.ts";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import { GalleryError, normalizeGalleryError } from "./errors.ts";
import type { GalleryService } from "./gallery-service.ts";
import type { InternalViewerContextCodec } from "./internal-auth.ts";
import type { GalleryPageRequest, ViewerContext } from "./types.ts";
import type { TaskCenterService } from "../tasks/task-center-service.ts";
import type { TaskListRequest, TaskModule } from "../tasks/types.ts";

export async function createGalleryHttpServer(options: {
  readonly service: GalleryService;
  readonly auth: InternalViewerContextCodec;
  readonly logger: StructuredLogger;
  readonly trustProxy?: boolean;
  readonly redis?: Redis;
  readonly admin?: AdminService;
  readonly billing?: BillingService;
  readonly generation?: GenerationService;
  readonly tasks?: TaskCenterService;
}): Promise<FastifyInstance> {
  const app = Fastify({ logger: false, trustProxy: options.trustProxy ?? false, bodyLimit: 16 * 1024 });
  await app.register(rateLimit, {
    global: true,
    max: 120,
    timeWindow: "1 minute",
    ...(options.redis ? { redis: options.redis } : {}),
    errorResponseBuilder: () => ({ error: { code: "rate_limited", message: "Too many Gallery requests" } }),
  });

  app.get("/health", async () => ({ status: "ok" }));

  app.get("/v1/gallery", async (request) => options.service.listPublic(parsePageRequest(request.query), viewer(request, options.auth)));
  app.get("/v1/gallery/:slug", async (request) => options.service.getBySlug(pathParam(request.params, "slug"), viewer(request, options.auth)));
  app.get("/v1/seo/images", { config: { rateLimit: { max: 20, timeWindow: "1 minute" } } }, async (request) => {
    viewer(request, options.auth);
    const page = parsePageRequest(request.query);
    return options.service.listSeoImages({ ...(page.cursor ? { cursor: page.cursor } : {}), ...(page.limit ? { limit: page.limit } : {}) });
  });
  app.get("/v1/me/images", async (request) => options.service.listMine(parsePageRequest(request.query), viewer(request, options.auth)));
  app.get("/v1/me/favorites", async (request) => options.service.listFavorites(parsePageRequest(request.query), viewer(request, options.auth)));

  if (options.generation) {
    app.get("/v1/generation/workflows", { config: { rateLimit: { max: 60, timeWindow: "1 minute" } } }, async (request) => {
      viewer(request, options.auth);
      return { items: await options.generation!.listWorkflows() };
    });
    app.get("/v1/generations", { config: { rateLimit: { max: 60, timeWindow: "1 minute" } } }, async (request) => {
      return options.generation!.list(parseGenerationListRequest(request.query), viewer(request, options.auth));
    });
    app.post("/v1/generations", { config: { rateLimit: { max: 10, timeWindow: "1 minute" } } }, async (request, reply) => {
      const result = await options.generation!.create(request.body, scalarHeader(request.headers["idempotency-key"]), viewer(request, options.auth));
      return reply.code(202).send(result);
    });
    app.get("/v1/generations/:id", { config: { rateLimit: { max: 120, timeWindow: "1 minute" } } }, async (request) => {
      return options.generation!.get(pathParam(request.params, "id"), viewer(request, options.auth));
    });
    app.delete("/v1/generations/:id", { config: { rateLimit: { max: 20, timeWindow: "1 minute" } } }, async (request) => {
      return options.generation!.cancel(pathParam(request.params, "id"), viewer(request, options.auth));
    });
  }

  if (options.tasks) {
    app.get("/v1/tasks", { config: { rateLimit: { max: 60, timeWindow: "1 minute" } } }, async (request) => {
      return options.tasks!.list(parseTaskListRequest(request.query), viewer(request, options.auth));
    });
  }

  if (options.billing) {
    app.get("/v1/billing/summary", { config: { rateLimit: { max: 60, timeWindow: "1 minute" } } }, async (request) => {
      const context = viewer(request, options.auth);
      return options.billing!.summary(context.userId);
    });
    app.post("/v1/billing/checkout", { config: { rateLimit: { max: 10, timeWindow: "1 minute" } } }, async (request) => {
      const context = viewer(request, options.auth);
      return options.billing!.checkout(context.userId, request.body);
    });
    app.post("/v1/billing/redeem", { config: { rateLimit: { max: 20, timeWindow: "1 minute" } } }, async (request) => {
      const context = viewer(request, options.auth);
      return options.billing!.redeem(context.userId, request.body);
    });
    app.post("/v1/billing/portal", { config: { rateLimit: { max: 10, timeWindow: "1 minute" } } }, async (request) => {
      const context = viewer(request, options.auth);
      return options.billing!.portal(context.userId);
    });
  }

  if (options.admin) {
    app.get("/v1/admin/dashboard", { config: { rateLimit: { max: 60, timeWindow: "1 minute" } } }, async (request) => options.admin!.dashboard(viewer(request, options.auth)));
    app.get("/v1/admin/queue", { config: { rateLimit: { max: 30, timeWindow: "1 minute" } } }, async (request) => options.admin!.queueSnapshot(viewer(request, options.auth)));
    app.patch("/v1/admin/images/:id/moderation", { config: { rateLimit: { max: 20, timeWindow: "1 minute" } } }, async (request) => options.admin!.moderateImage(pathParam(request.params, "id"), request.body, viewer(request, options.auth)));
    app.patch("/v1/admin/providers/:id", { config: { rateLimit: { max: 20, timeWindow: "1 minute" } } }, async (request) => options.admin!.updateProvider(pathParam(request.params, "id"), request.body, viewer(request, options.auth)));
    app.patch("/v1/admin/provider-models/:id", { config: { rateLimit: { max: 40, timeWindow: "1 minute" } } }, async (request) => options.admin!.updateProviderModel(pathParam(request.params, "id"), request.body, viewer(request, options.auth)));
    app.patch("/v1/admin/workflows/:id", { config: { rateLimit: { max: 20, timeWindow: "1 minute" } } }, async (request) => options.admin!.updateWorkflow(pathParam(request.params, "id"), request.body, viewer(request, options.auth)));
  }

  app.put("/v1/images/:id/favorite", { config: { rateLimit: { max: 30, timeWindow: "1 minute" } } }, async (request) => options.service.setFavorite(pathParam(request.params, "id"), true, viewer(request, options.auth)));
  app.delete("/v1/images/:id/favorite", { config: { rateLimit: { max: 30, timeWindow: "1 minute" } } }, async (request) => options.service.setFavorite(pathParam(request.params, "id"), false, viewer(request, options.auth)));
  app.put("/v1/images/:id/like", { config: { rateLimit: { max: 30, timeWindow: "1 minute" } } }, async (request) => options.service.setLike(pathParam(request.params, "id"), true, viewer(request, options.auth)));
  app.delete("/v1/images/:id/like", { config: { rateLimit: { max: 30, timeWindow: "1 minute" } } }, async (request) => options.service.setLike(pathParam(request.params, "id"), false, viewer(request, options.auth)));
  app.delete("/v1/images/:id", { config: { rateLimit: { max: 10, timeWindow: "1 minute" } } }, async (request, reply) => {
    await options.service.deleteImage(pathParam(request.params, "id"), viewer(request, options.auth));
    return reply.code(204).send();
  });
  app.post("/v1/images/:id/download", { config: { rateLimit: { max: 30, timeWindow: "1 minute" } } }, async (request) => options.service.grantDownload(
    pathParam(request.params, "id"),
    viewer(request, options.auth),
    request.ip,
    scalarHeader(request.headers["user-agent"]),
  ));

  app.setErrorHandler((error, request, reply) => {
    const candidateStatus = error && typeof error === "object" && "statusCode" in error && typeof error.statusCode === "number" ? error.statusCode : 500;
    const generationRequest = request.url.startsWith("/v1/generation");
    const normalized = error instanceof GalleryError || error instanceof BillingError || error instanceof GenerationError
      ? error
      : candidateStatus >= 400 && candidateStatus < 500
        ? new GalleryError("invalid_request", "The Gallery request is invalid", candidateStatus)
        : generationRequest ? normalizeGenerationError(error) : normalizeGalleryError(error);
    options.logger.error("gallery.request_failed", { requestId: request.id, code: normalized.code, statusCode: normalized.statusCode });
    return reply.code(normalized.statusCode).send({ error: { code: normalized.code, message: normalized.message } });
  });
  return app;
}

function viewer(request: FastifyRequest, auth: InternalViewerContextCodec): ViewerContext {
  return auth.verify(request.headers);
}

function parsePageRequest(value: unknown): GalleryPageRequest {
  const query = record(value);
  const orientation = scalar(query.orientation);
  if (orientation && !new Set(["portrait", "square", "landscape"]).has(orientation)) throw new GalleryError("invalid_request", "orientation is invalid", 400);
  const cursor = scalar(query.cursor);
  const limit = scalar(query.limit);
  const search = scalar(query.q);
  const tag = scalar(query.tag);
  const workflow = scalar(query.workflow);
  return {
    ...(cursor ? { cursor } : {}),
    ...(limit ? { limit: Number(limit) } : {}),
    ...(search ? { query: search } : {}),
    ...(tag ? { tag } : {}),
    ...(workflow ? { workflow } : {}),
    ...(orientation ? { orientation: orientation as "portrait" | "square" | "landscape" } : {}),
  };
}

function parseGenerationListRequest(value: unknown): GenerationListRequest {
  const query = record(value);
  const cursor = scalar(query.cursor);
  const limit = scalar(query.limit);
  const status = scalar(query.status);
  return {
    ...(cursor ? { cursor } : {}),
    ...(limit ? { limit: Number(limit) } : {}),
    ...(status ? { status: status as GenerationStatus } : {}),
  };
}

function parseTaskListRequest(value: unknown): TaskListRequest {
  const query = record(value);
  const module = scalar(query.module);
  const cursor = scalar(query.cursor);
  const limit = scalar(query.limit);
  const status = scalar(query.status);
  return {
    ...(module ? { module: module as TaskModule } : {}),
    ...(cursor ? { cursor } : {}),
    ...(limit ? { limit: Number(limit) } : {}),
    ...(status ? { status: status as GenerationStatus } : {}),
  };
}

function pathParam(value: unknown, key: string): string {
  const result = scalar(record(value)[key]);
  return result ?? "";
}
function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function scalar(value: unknown): string | undefined { return typeof value === "string" ? value : undefined; }
function scalarHeader(value: string | string[] | undefined): string | undefined { return Array.isArray(value) ? undefined : value; }
