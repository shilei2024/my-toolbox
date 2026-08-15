import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { Pool } from "pg";
import { CreditService } from "../src/billing/credit-service.ts";
import { normalizeStripeEvent } from "../src/billing/stripe-provider.ts";
import { PostgresBillingRepository } from "../src/billing/postgres-billing-repository.ts";

const databaseUrl = process.env.PHASE10_TEST_DATABASE_URL;
const USER_ID = 9010;
const WORKFLOW_ID = "a13e4567-e89b-42d3-a456-426614174000";
const VERSION_ID = "a23e4567-e89b-42d3-a456-426614174000";
const JOB_ID = "a33e4567-e89b-42d3-a456-426614174000";
const ORDER_ID = "b13e4567-e89b-42d3-a456-426614174000";
const PLAN_ID = "c13e4567-e89b-42d3-a456-426614174000";

describe("Phase 10 PostgreSQL credit ledger", { skip: !databaseUrl }, () => {
  const pool = new Pool({ connectionString: databaseUrl });
  const credits = new CreditService(pool);

  before(async () => {
    await pool.query("INSERT INTO public.users (id, email) VALUES ($1, 'phase10-billing@example.test')", [USER_ID]);
    await pool.query("INSERT INTO ai.workflows (id, slug, name, category, is_enabled) VALUES ($1, 'phase10-credit-test', 'Phase 10', 'test', true)", [WORKFLOW_ID]);
    await pool.query("INSERT INTO ai.workflow_versions (id, workflow_id, version, is_active) VALUES ($1, $2, 1, true)", [VERSION_ID, WORKFLOW_ID]);
    await pool.query(`INSERT INTO ai.generation_jobs (id, user_id, workflow_version_id, prompt, requested_width, requested_height)
      VALUES ($1, $2, $3, 'credit test', 512, 512)`, [JOB_ID, USER_ID, VERSION_ID]);
    await pool.query("INSERT INTO ai.credit_accounts (user_id, available_amount, lifetime_granted) VALUES ($1, 20, 20)", [USER_ID]);
  });

  after(async () => {
    await pool.end();
  });

  it("atomically reserves and settles generation credits", async () => {
    assert.deepEqual(await credits.reserve(USER_ID, JOB_ID, "5.0000", "reserve-job-1"), { availableAmount: "15.0000", reservedAmount: "5.0000" });
    assert.deepEqual(await credits.reserve(USER_ID, JOB_ID, "5.0000", "reserve-job-1"), { availableAmount: "15.0000", reservedAmount: "5.0000" });
    assert.deepEqual(await credits.settle(JOB_ID, "4.0000", "settle-job-1"), { availableAmount: "16.0000", reservedAmount: "0.0000" });
    const account = (await pool.query<{ lifetime_spent: string }>("SELECT lifetime_spent FROM ai.credit_accounts WHERE user_id = $1", [USER_ID])).rows[0];
    assert.equal(account?.lifetime_spent, "4.0000");
  });

  it("prevents ledger mutation", async () => {
    await assert.rejects(pool.query("UPDATE ai.credit_ledger_entries SET metadata = '{}' WHERE user_id = $1", [USER_ID]), /immutable/);
  });

  it("normalizes both Stripe success events for one order to the same order reference", () => {
    // checkout.session.completed and payment_intent.succeeded for the same
    // synchronous payment are two distinct Stripe events. Both must resolve to
    // the same orderId so order-anchored crediting stays idempotent.
    const checkout = normalizeStripeEvent({
      id: "evt_checkout_1", created: 1_786_000_000, type: "checkout.session.completed",
      data: { object: { id: "cs_1", mode: "payment", payment_status: "paid", payment_intent: "pi_1", metadata: { order_id: ORDER_ID } } },
    } as never);
    const intent = normalizeStripeEvent({
      id: "evt_intent_1", created: 1_786_000_001, type: "payment_intent.succeeded",
      data: { object: { id: "pi_1", metadata: { order_id: ORDER_ID } } },
    } as never);
    assert.equal(checkout.eventType, "checkout.completed");
    assert.equal(intent.eventType, "checkout.completed");
    assert.equal(checkout.data.orderId, ORDER_ID);
    assert.equal(intent.data.orderId, ORDER_ID);
  });

  it("credits a credit pack exactly once when both Stripe events are processed", async () => {
    const repository = new PostgresBillingRepository(pool);
    await pool.query(`INSERT INTO ai.billing_plans (id, slug, name, description, kind, currency, amount_minor, credit_amount, is_enabled, is_public)
      VALUES ($1, 'phase10-pack', 'Phase 10 Pack', '', 'credit_pack', 'cny', '100', '20.0000', true, false)`, [PLAN_ID]);
    await pool.query(`INSERT INTO ai.payment_orders (id, user_id, plan_id, payment_provider, idempotency_key, status, amount_minor)
      VALUES ($1, $2, $3, 'stripe', 'pack-idem-1', 'paid', '100')`, [ORDER_ID, USER_ID, PLAN_ID]);
    const before = (await pool.query<{ available_amount: string }>("SELECT available_amount FROM ai.credit_accounts WHERE user_id = $1", [USER_ID])).rows[0]?.available_amount ?? "0";
    const eventA: Parameters<typeof repository.recordWebhook>[0] = { provider: "stripe", externalEventId: "evt_checkout_1", eventType: "checkout.completed", eventCreatedAt: "2026-08-02T00:00:00.000Z", data: { orderId: ORDER_ID, paymentStatus: "paid", mode: "payment" } };
    const eventB: Parameters<typeof repository.recordWebhook>[0] = { provider: "stripe", externalEventId: "evt_intent_1", eventType: "checkout.completed", eventCreatedAt: "2026-08-02T00:00:01.000Z", data: { orderId: ORDER_ID, paymentId: "pi_1", paymentStatus: "paid", mode: "payment" } };
    await repository.recordWebhook(eventA, "sha-a");
    await repository.recordWebhook(eventB, "sha-b");
    const claimed = await repository.claimWebhookEvents(10);
    const processor = { id: "inbox-x", event: eventA, attempt: 1 };
    await repository.processWebhookEvent(processor);
    await repository.processWebhookEvent({ id: "inbox-x", event: eventB, attempt: 1 });
    const afterCredits = (await pool.query<{ available_amount: string }>("SELECT available_amount FROM ai.credit_accounts WHERE user_id = $1", [USER_ID])).rows[0]?.available_amount ?? "0";
    // Both events target the same order; the pack must be granted exactly once.
    assert.equal(Number(afterCredits) - Number(before), 20);
    assert.equal(claimed.length >= 1, true);
  });
});
