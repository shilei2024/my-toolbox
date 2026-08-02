import rateLimit from "@fastify/rate-limit";
import Fastify, { type FastifyInstance } from "fastify";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import type { BillingService } from "./billing-service.ts";
import { BillingError, normalizeBillingError } from "./errors.ts";

export async function createBillingWebhookHttpServer(options: { service: BillingService; logger: StructuredLogger; trustProxy?: boolean }): Promise<FastifyInstance> {
  const app = Fastify({ logger: false, trustProxy: options.trustProxy ?? false, bodyLimit: 256 * 1024 });
  app.addContentTypeParser("application/json", { parseAs: "buffer" }, (_request, body, done) => done(null, body));
  await app.register(rateLimit, { global: true, max: 180, timeWindow: "1 minute", errorResponseBuilder: () => ({ error: { code: "rate_limited", message: "Too many webhook requests" } }) });
  app.get("/health", async () => ({ status: "ok" }));
  app.post("/v1/billing/webhooks/:provider", async (request, reply) => {
    const provider = scalar(record(request.params).provider) ?? "";
    const signature = provider === "stripe" ? scalarHeader(request.headers["stripe-signature"]) : scalarHeader(request.headers["x-payment-signature"]);
    const result = await options.service.receiveWebhook(provider, request.body as Buffer, signature);
    return reply.code(202).send(result);
  });
  app.setErrorHandler((error, request, reply) => {
    const normalized = error instanceof BillingError ? error : normalizeBillingError(error);
    options.logger.error("billing.webhook_request_failed", { requestId: request.id, code: normalized.code, statusCode: normalized.statusCode });
    return reply.code(normalized.statusCode).send({ error: { code: normalized.code, message: normalized.message } });
  });
  return app;
}
function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function scalar(value: unknown): string | undefined { return typeof value === "string" ? value : undefined; }
function scalarHeader(value: string | string[] | undefined): string | undefined { return Array.isArray(value) ? undefined : value; }

