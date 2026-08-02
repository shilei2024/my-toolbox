import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { BillingService, BillingWebhookProcessor } from "../src/billing/billing-service.ts";
import { loadBillingConfig } from "../src/billing/config.ts";
import { PaymentProviderRegistry, type PaymentProvider } from "../src/billing/payment-provider.ts";
import type { BillingRepository } from "../src/billing/repository.ts";
import { normalizeStripeEvent } from "../src/billing/stripe-provider.ts";
import type { BillingPlan, BillingSummary, NormalizedPaymentEvent, PaymentOrder, StoredPaymentEvent } from "../src/billing/types.ts";

const plan: BillingPlan = {
  id: "plan-1", slug: "creator-monthly", displayName: "Creator", description: "", kind: "subscription",
  billingInterval: "month", currency: "USD", amountMinor: "1200", creditAmount: "100.0000", entitlements: {},
  paymentProvider: "fakepay", externalPriceRef: "price_creator",
};

class FakeRepository implements BillingRepository {
  readonly received: NormalizedPaymentEvent[] = [];
  readonly processed: string[] = [];
  readonly failed: string[] = [];
  claimed: StoredPaymentEvent[] = [];
  checkout?: { orderId: string; externalId: string };
  summary(): Promise<BillingSummary> { return Promise.resolve({ plans: [plan], account: { availableAmount: "42.0000", reservedAmount: "3.0000", lifetimeGranted: "50.0000", lifetimeSpent: "5.0000" }, subscription: { planSlug: plan.slug, planName: plan.displayName, provider: "fakepay", status: "active", cancelAtPeriodEnd: false }, ledger: [] }); }
  createOrGetOrder(userId: number, _planSlug: string, idempotencyKey: string): Promise<PaymentOrder> { return Promise.resolve({ id: "order-1", userId, plan, provider: "fakepay", idempotencyKey, status: "created" }); }
  customerReference(): Promise<string | undefined> { return Promise.resolve("cus-1"); }
  markCheckoutOpen(orderId: string, externalCheckoutId: string): Promise<void> { this.checkout = { orderId, externalId: externalCheckoutId }; return Promise.resolve(); }
  recordWebhook(event: NormalizedPaymentEvent): Promise<boolean> { const duplicate = this.received.some((item) => item.externalEventId === event.externalEventId); if (!duplicate) this.received.push(event); return Promise.resolve(!duplicate); }
  claimWebhookEvents(): Promise<readonly StoredPaymentEvent[]> { return Promise.resolve(this.claimed); }
  processWebhookEvent(event: StoredPaymentEvent): Promise<void> { this.processed.push(event.id); return Promise.resolve(); }
  failWebhookEvent(id: string): Promise<void> { this.failed.push(id); return Promise.resolve(); }
}

class FakeProvider implements PaymentProvider {
  readonly code = "fakepay";
  createCheckout(): Promise<{ externalSessionId: string; url: string }> { return Promise.resolve({ externalSessionId: "checkout-1", url: "https://pay.example.test/session/1" }); }
  createCustomerPortal(): Promise<{ url: string }> { return Promise.resolve({ url: "https://pay.example.test/portal/1" }); }
  verifyAndNormalizeWebhook(): NormalizedPaymentEvent { return { provider: this.code, externalEventId: "event-1", eventType: "ignored", eventCreatedAt: "2026-08-02T00:00:00.000Z", data: { originalType: "test.event" } }; }
}

const logger = { info() {}, error() {} };

describe("Phase 10 billing boundary", () => {
  it("creates hosted checkout without exposing provider details to the caller", async () => {
    const repository = new FakeRepository(); const providers = new PaymentProviderRegistry(); providers.register(new FakeProvider());
    const service = new BillingService({ repository, providers, logger, publicBaseUrl: "https://mindfulpenpal.com" });
    assert.deepEqual(await service.checkout(7, { planSlug: plan.slug, idempotencyKey: "checkout-attempt-1" }), { url: "https://pay.example.test/session/1" });
    assert.deepEqual(repository.checkout, { orderId: "order-1", externalId: "checkout-1" });
  });

  it("verifies a webhook before storing a minimal idempotent inbox event", async () => {
    const repository = new FakeRepository(); const providers = new PaymentProviderRegistry(); providers.register(new FakeProvider());
    const service = new BillingService({ repository, providers, logger, publicBaseUrl: "https://mindfulpenpal.com" });
    assert.deepEqual(await service.receiveWebhook("fakepay", Buffer.from("{}"), "signed"), { accepted: true });
    assert.deepEqual(await service.receiveWebhook("fakepay", Buffer.from("{}"), "signed"), { accepted: false });
    assert.equal(repository.received.length, 1);
  });

  it("normalizes Stripe payloads inside the adapter boundary", () => {
    const event = normalizeStripeEvent({
      id: "evt_1", created: 1_786_000_000, type: "checkout.session.completed",
      data: { object: { id: "cs_1", mode: "subscription", payment_status: "paid", customer: "cus_1", subscription: "sub_1", metadata: { order_id: "order-1" } } },
    } as never);
    assert.equal(event.eventType, "checkout.completed");
    assert.equal(event.data.orderId, "order-1");
    assert.equal("subscriptionId" in event.data ? event.data.subscriptionId : undefined, "sub_1");
  });

  it("keeps Stripe disabled by default and rejects partial secret configuration", () => {
    assert.equal(loadBillingConfig({}).stripe, undefined);
    assert.throws(() => loadBillingConfig({ BILLING_STRIPE_ENABLED: "true", STRIPE_SECRET_KEY: "sk_test_only" }), /STRIPE_SECRET_KEY/);
  });

  it("processes claimed webhook inbox records independently of HTTP receipt", async () => {
    const repository = new FakeRepository();
    repository.claimed = [{ id: "inbox-1", attempt: 1, event: { provider: "fakepay", externalEventId: "event-1", eventType: "ignored", eventCreatedAt: "2026-08-02T00:00:00.000Z", data: { originalType: "unused" } } }];
    assert.equal(await new BillingWebhookProcessor(repository, logger).runOnce(), 1);
    assert.deepEqual(repository.processed, ["inbox-1"]);
  });
});
