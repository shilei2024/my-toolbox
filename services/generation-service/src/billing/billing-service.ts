import { createHash } from "node:crypto";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import { BillingError } from "./errors.ts";
import { PaymentProviderRegistry } from "./payment-provider.ts";
import type { BillingRepository } from "./repository.ts";
import type { BillingSummary } from "./types.ts";

export class BillingService {
  readonly #repository: BillingRepository;
  readonly #providers: PaymentProviderRegistry;
  readonly #logger: StructuredLogger;
  readonly #publicBaseUrl: string;

  constructor(options: { repository: BillingRepository; providers: PaymentProviderRegistry; logger: StructuredLogger; publicBaseUrl: string }) {
    this.#repository = options.repository;
    this.#providers = options.providers;
    this.#logger = options.logger;
    this.#publicBaseUrl = options.publicBaseUrl.replace(/\/$/, "");
  }

  summary(userId?: number): Promise<BillingSummary> {
    return this.#repository.summary(userId);
  }

  async checkout(userId: number | undefined, input: unknown): Promise<{ readonly url: string }> {
    if (!userId) throw new BillingError("authentication_required", "Authentication is required", 401);
    const body = record(input);
    const planSlug = boundedString(body.planSlug, 80, "planSlug");
    const idempotencyKey = boundedString(body.idempotencyKey, 128, "idempotencyKey");
    const order = await this.#repository.createOrGetOrder(userId, planSlug, idempotencyKey);
    const provider = this.#providers.get(order.provider);
    if (!provider) throw new BillingError("payment_provider_unavailable", "This payment method is not available", 503);
    if (order.externalCheckoutId && order.externalCheckoutUrl) { assertHostedUrl(order.externalCheckoutUrl); return { url: order.externalCheckoutUrl }; }
    if (order.externalCheckoutId) throw new BillingError("checkout_state_conflict", "Checkout state is incomplete", 409);
    const customer = await this.#repository.customerReference(userId, provider.code);
    const session = await provider.createCheckout({
      order,
      ...(customer ? { externalCustomerId: customer } : {}),
      successUrl: `${this.#publicBaseUrl}/billing?checkout=success&session_id={CHECKOUT_SESSION_ID}`,
      cancelUrl: `${this.#publicBaseUrl}/pricing?checkout=cancelled`,
    });
    assertHostedUrl(session.url);
    await this.#repository.markCheckoutOpen(order.id, session.externalSessionId, session.url, session.expiresAt);
    this.#logger.info("billing.checkout_created", { userId, orderId: order.id, provider: provider.code });
    return { url: session.url };
  }

  async portal(userId: number | undefined): Promise<{ readonly url: string }> {
    if (!userId) throw new BillingError("authentication_required", "Authentication is required", 401);
    const summary = await this.#repository.summary(userId);
    const providerCode = summary.subscription?.provider;
    if (!providerCode) throw new BillingError("billing_customer_not_found", "No managed subscription was found", 409);
    const provider = this.#providers.get(providerCode);
    const customer = provider ? await this.#repository.customerReference(userId, providerCode) : undefined;
    if (!provider || !customer) throw new BillingError("payment_provider_unavailable", "Subscription management is unavailable", 503);
    const result = await provider.createCustomerPortal({ externalCustomerId: customer, returnUrl: `${this.#publicBaseUrl}/billing` });
    assertHostedUrl(result.url);
    return result;
  }

  async receiveWebhook(providerCode: string, rawBody: Buffer, signature: string | undefined): Promise<{ readonly accepted: boolean }> {
    const provider = this.#providers.get(providerCode);
    if (!provider) throw new BillingError("payment_provider_not_found", "Payment provider is not configured", 404);
    if (!signature) throw new BillingError("webhook_signature_missing", "Webhook signature is missing", 400);
    let event;
    try {
      event = provider.verifyAndNormalizeWebhook(rawBody, signature);
    } catch {
      throw new BillingError("webhook_signature_invalid", "Webhook signature is invalid", 400);
    }
    const accepted = await this.#repository.recordWebhook(event, createHash("sha256").update(rawBody).digest("hex"));
    this.#logger.info("billing.webhook_received", { provider: providerCode, eventId: event.externalEventId, eventType: event.eventType, duplicate: !accepted });
    return { accepted };
  }
}

export class BillingWebhookProcessor {
  readonly #repository: BillingRepository;
  readonly #logger: StructuredLogger;
  constructor(repository: BillingRepository, logger: StructuredLogger) { this.#repository = repository; this.#logger = logger; }

  async runOnce(limit = 20): Promise<number> {
    const events = await this.#repository.claimWebhookEvents(Math.max(1, Math.min(limit, 100)));
    for (const event of events) {
      try {
        await this.#repository.processWebhookEvent(event);
      } catch (error) {
        const backoffSeconds = Math.min(3600, 2 ** Math.min(event.attempt, 10));
        await this.#repository.failWebhookEvent(event.id, safeErrorCode(error), new Date(Date.now() + backoffSeconds * 1000));
        this.#logger.error("billing.webhook_processing_failed", { eventId: event.event.externalEventId, attempt: event.attempt, errorCode: safeErrorCode(error) });
      }
    }
    return events.length;
  }
}

function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function boundedString(value: unknown, max: number, field: string): string {
  if (typeof value !== "string" || value.length < 1 || value.length > max) throw new BillingError("invalid_request", `${field} is invalid`, 400);
  return value;
}
function assertHostedUrl(value: string): void {
  const url = new URL(value);
  if (url.protocol !== "https:") throw new BillingError("invalid_provider_response", "Payment provider returned an invalid URL", 502);
}
function safeErrorCode(error: unknown): string {
  if (error && typeof error === "object" && "code" in error && typeof error.code === "string") return error.code.slice(0, 80);
  return "processing_failed";
}
