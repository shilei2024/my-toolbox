import Stripe from "stripe";
import type { PaymentProvider } from "./payment-provider.ts";
import type { NormalizedPaymentEvent, SubscriptionStatus } from "./types.ts";

export class StripePaymentProvider implements PaymentProvider {
  readonly code = "stripe";
  readonly #client: Stripe;
  readonly #webhookSecret: string;

  constructor(webhookSecret: string, secretKey: string, options: { maxNetworkRetries?: number; timeoutMs?: number } = {}) {
    this.#webhookSecret = webhookSecret;
    this.#client = new Stripe(secretKey, {
      maxNetworkRetries: options.maxNetworkRetries ?? 2,
      timeout: options.timeoutMs ?? 20_000,
      telemetry: false,
    });
  }

  async createCheckout(input: Parameters<PaymentProvider["createCheckout"]>[0]): Promise<{ externalSessionId: string; url: string; expiresAt?: string }> {
    const mode = input.order.plan.kind === "subscription" ? "subscription" : "payment";
    const session = await this.#client.checkout.sessions.create({
      mode,
      line_items: [{ price: input.order.plan.externalPriceRef!, quantity: 1 }],
      client_reference_id: input.order.id,
      metadata: { order_id: input.order.id, plan_slug: input.order.plan.slug },
      success_url: input.successUrl,
      cancel_url: input.cancelUrl,
      allow_promotion_codes: true,
      ...(input.externalCustomerId ? { customer: input.externalCustomerId } : {}),
      ...(mode === "subscription" ? { subscription_data: { metadata: { order_id: input.order.id, plan_slug: input.order.plan.slug } } } : {}),
    }, { idempotencyKey: input.order.id });
    if (!session.url) throw new Error("stripe_checkout_url_missing");
    return { externalSessionId: session.id, url: session.url, ...(session.expires_at ? { expiresAt: fromUnix(session.expires_at) } : {}) };
  }

  async createCustomerPortal(input: Parameters<PaymentProvider["createCustomerPortal"]>[0]): Promise<{ readonly url: string }> {
    const session = await this.#client.billingPortal.sessions.create({ customer: input.externalCustomerId, return_url: input.returnUrl });
    return { url: session.url };
  }

  verifyAndNormalizeWebhook(rawBody: Buffer, signature: string): NormalizedPaymentEvent {
    return normalizeStripeEvent(this.#client.webhooks.constructEvent(rawBody, signature, this.#webhookSecret));
  }
}

export function normalizeStripeEvent(event: Stripe.Event): NormalizedPaymentEvent {
  const base = { provider: "stripe" as const, externalEventId: event.id, eventCreatedAt: fromUnix(event.created) };
  const object = record(event.data.object);
  if (event.type === "checkout.session.completed") {
    const mode = scalar(object.mode);
    const customerId = id(object.customer);
    const subscriptionId = id(object.subscription);
    const paymentId = id(object.payment_intent);
    return { ...base, eventType: "checkout.completed", data: {
      orderId: scalar(record(object.metadata).order_id) ?? scalar(object.client_reference_id) ?? "",
      ...(customerId ? { customerId } : {}),
      ...(subscriptionId ? { subscriptionId } : {}),
      ...(paymentId ? { paymentId } : {}),
      paymentStatus: scalar(object.payment_status) ?? "unpaid",
      mode: mode === "subscription" || mode === "setup" ? mode : "payment",
    } };
  }
  if (event.type === "invoice.paid" || event.type === "invoice.payment_failed") {
    const customerId = id(object.customer);
    const subscriptionId = invoiceSubscriptionId(object);
    return { ...base, eventType: event.type === "invoice.paid" ? "invoice.paid" : "invoice.payment_failed", data: {
      invoiceId: scalar(object.id) ?? event.id,
      ...(customerId ? { customerId } : {}),
      ...(subscriptionId ? { subscriptionId } : {}),
    } };
  }
  if (event.type.startsWith("customer.subscription.")) {
    const firstItem = array(record(object.items).data)[0];
    const item = record(firstItem);
    const periodStart = integer(object.current_period_start) ?? integer(item.current_period_start);
    const periodEnd = integer(object.current_period_end) ?? integer(item.current_period_end);
    const customerId = id(object.customer);
    const externalPriceRef = id(record(item.price).id);
    return { ...base, eventType: "subscription.changed", data: {
      subscriptionId: scalar(object.id) ?? event.id,
      ...(customerId ? { customerId } : {}),
      ...(externalPriceRef ? { externalPriceRef } : {}),
      status: mapSubscriptionStatus(scalar(object.status), event.type),
      cancelAtPeriodEnd: object.cancel_at_period_end === true,
      ...(periodStart ? { currentPeriodStart: fromUnix(periodStart) } : {}),
      ...(periodEnd ? { currentPeriodEnd: fromUnix(periodEnd) } : {}),
    } };
  }
  if (event.type === "charge.refunded") {
    return { ...base, eventType: "payment.refunded", data: {
      paymentId: id(object.payment_intent) ?? scalar(object.id) ?? "",
      amountMinor: String(integer(object.amount) ?? 0),
      refundedAmountMinor: String(integer(object.amount_refunded) ?? 0),
    } };
  }
  return { ...base, eventType: "ignored", data: { originalType: event.type } };
}

function invoiceSubscriptionId(object: Record<string, unknown>): string | undefined {
  return id(object.subscription)
    ?? id(record(record(object.parent).subscription_details).subscription)
    ?? id(record(record(object.subscription_details).subscription).id);
}
function mapSubscriptionStatus(value: string | undefined, eventType: string): SubscriptionStatus {
  if (eventType === "customer.subscription.deleted") return "cancelled";
  if (value === "trialing" || value === "active" || value === "past_due" || value === "paused" || value === "unpaid" || value === "incomplete") return value;
  return value === "canceled" ? "cancelled" : "incomplete";
}
function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function scalar(value: unknown): string | undefined { return typeof value === "string" ? value : undefined; }
function integer(value: unknown): number | undefined { return typeof value === "number" && Number.isInteger(value) ? value : undefined; }
function array(value: unknown): readonly unknown[] { return Array.isArray(value) ? value : []; }
function id(value: unknown): string | undefined { return typeof value === "string" ? value : scalar(record(value).id); }
function fromUnix(value: number): string { return new Date(value * 1000).toISOString(); }
