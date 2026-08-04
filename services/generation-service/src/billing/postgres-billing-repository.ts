import type { Pool, PoolClient, QueryResultRow } from "pg";
import { BillingError } from "./errors.ts";
import type { BillingRepository } from "./repository.ts";
import type { BillingPlan, BillingSummary, NormalizedPaymentEvent, PaymentOrder, StoredPaymentEvent, SubscriptionStatus } from "./types.ts";

interface PlanRow extends QueryResultRow {
  id: string; slug: string; display_name: string; description: string; kind: BillingPlan["kind"];
  billing_interval: "month" | "year" | null; currency: string; amount_minor: string; credit_amount: string;
  entitlements: Record<string, unknown>; payment_provider: string | null; external_price_ref: string | null;
}

export class PostgresBillingRepository implements BillingRepository {
  readonly #pool: Pool;
  constructor(pool: Pool) { this.#pool = pool; }

  async summary(userId?: number): Promise<BillingSummary> {
    const plans = (await this.#pool.query<PlanRow>(`${planSelect}
      WHERE is_enabled AND is_public ORDER BY sort_order, slug`)).rows.map(mapPlan);
    if (!userId) return { plans, ledger: [] };
    const [account, subscription, ledger] = await Promise.all([
      this.#pool.query<{ available_amount: string; reserved_amount: string; lifetime_granted: string; lifetime_spent: string }>(
        "SELECT available_amount, reserved_amount, lifetime_granted, lifetime_spent FROM ai.credit_accounts WHERE user_id = $1", [userId]),
      this.#pool.query<{ plan_slug: string; plan_name: string; payment_provider: string; status: SubscriptionStatus; cancel_at_period_end: boolean; current_period_end: Date | string | null }>(`SELECT p.slug AS plan_slug, p.display_name AS plan_name,
          s.payment_provider, s.status, s.cancel_at_period_end, s.current_period_end
        FROM ai.subscriptions s JOIN ai.billing_plans p ON p.id = s.plan_id
        WHERE s.user_id = $1 ORDER BY
          CASE WHEN s.status IN ('trialing', 'active', 'past_due') THEN 0 ELSE 1 END,
          s.updated_at DESC LIMIT 1`, [userId]),
      this.#pool.query<{ id: string; entry_type: string; delta_available: string; delta_reserved: string; source_type: string; source_ref: string; created_at: Date | string }>(`SELECT id, entry_type, delta_available, delta_reserved, source_type, source_ref, created_at
        FROM ai.credit_ledger_entries WHERE user_id = $1 ORDER BY created_at DESC, id DESC LIMIT 30`, [userId]),
    ]);
    const accountRow = account.rows[0];
    const subscriptionRow = subscription.rows[0];
    return {
      plans,
      account: accountRow
        ? { availableAmount: accountRow.available_amount, reservedAmount: accountRow.reserved_amount, lifetimeGranted: accountRow.lifetime_granted, lifetimeSpent: accountRow.lifetime_spent }
        : { availableAmount: "0.0000", reservedAmount: "0.0000", lifetimeGranted: "0.0000", lifetimeSpent: "0.0000" },
      ...(subscriptionRow ? { subscription: {
        planSlug: subscriptionRow.plan_slug,
        planName: subscriptionRow.plan_name,
        provider: subscriptionRow.payment_provider,
        status: subscriptionRow.status,
        cancelAtPeriodEnd: subscriptionRow.cancel_at_period_end,
        ...(subscriptionRow.current_period_end ? { currentPeriodEnd: iso(subscriptionRow.current_period_end) } : {}),
      } } : {}),
      ledger: ledger.rows.map((row) => ({
        id: row.id, entryType: row.entry_type, deltaAvailable: row.delta_available, deltaReserved: row.delta_reserved,
        sourceType: row.source_type, sourceRef: row.source_ref, createdAt: iso(row.created_at),
      })),
    };
  }

  async ensureSignupGrant(userId: number, amount: string): Promise<void> {
    if (Number(amount) <= 0) return;
    await this.transaction(async (client) => {
      await grantCredits(client, userId, amount, "signup_grant", "system", "signup", `signup-grant:${userId}`);
    });
  }

  async createOrGetOrder(userId: number, planSlug: string, idempotencyKey: string): Promise<PaymentOrder> {
    return this.transaction(async (client) => {
      const planResult = await client.query<PlanRow>(`${planSelect} WHERE slug = $1 AND is_enabled AND is_public FOR SHARE`, [planSlug]);
      const plan = planResult.rows[0];
      if (!plan || plan.kind === "free" || !plan.payment_provider || !plan.external_price_ref) throw new BillingError("plan_not_available", "This plan is not available for checkout", 404);
      const existing = await client.query<OrderRow>(`${orderSelect} WHERE o.user_id = $1 AND o.idempotency_key = $2`, [userId, idempotencyKey]);
      const found = existing.rows[0];
      if (found) {
        if (found.plan_id !== plan.id) throw new BillingError("idempotency_conflict", "Idempotency key was already used for another plan", 409);
        return mapOrder(found, mapPlan(plan));
      }
      if (plan.kind === "subscription") {
        const live = await client.query("SELECT 1 FROM ai.subscriptions WHERE user_id = $1 AND status IN ('incomplete', 'trialing', 'active', 'past_due', 'paused', 'unpaid') LIMIT 1", [userId]);
        if (live.rowCount) throw new BillingError("subscription_already_exists", "Manage the existing subscription instead of creating another one", 409);
      }
      const inserted = await client.query<OrderRow>(`INSERT INTO ai.payment_orders (
          user_id, plan_id, payment_provider, idempotency_key, currency, amount_minor
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (user_id, idempotency_key) DO NOTHING
        RETURNING id, user_id, plan_id, payment_provider, idempotency_key, status, external_checkout_id, external_checkout_url`,
      [userId, plan.id, plan.payment_provider, idempotencyKey, plan.currency, plan.amount_minor]);
      const created = inserted.rows[0];
      if (created) return mapOrder(created, mapPlan(plan));
      const raced = (await client.query<OrderRow>(`${orderSelect} WHERE o.user_id = $1 AND o.idempotency_key = $2`, [userId, idempotencyKey])).rows[0];
      if (!raced || raced.plan_id !== plan.id) throw new BillingError("idempotency_conflict", "Idempotency key was already used for another plan", 409);
      return mapOrder(raced, mapPlan(plan));
    });
  }

  async customerReference(userId: number, provider: string): Promise<string | undefined> {
    return (await this.#pool.query<{ external_customer_id: string }>(
      "SELECT external_customer_id FROM ai.billing_customers WHERE user_id = $1 AND payment_provider = $2", [userId, provider])).rows[0]?.external_customer_id;
  }

  async markCheckoutOpen(orderId: string, externalCheckoutId: string, checkoutUrl: string, expiresAt?: string): Promise<void> {
    const result = await this.#pool.query(`UPDATE ai.payment_orders SET status = 'checkout_open', external_checkout_id = $2, external_checkout_url = $3, expires_at = $4
      WHERE id = $1 AND status = 'created'`, [orderId, externalCheckoutId, checkoutUrl, expiresAt ?? null]);
    if (result.rowCount !== 1) throw new BillingError("checkout_state_conflict", "Checkout state changed", 409);
  }

  async recordWebhook(event: NormalizedPaymentEvent, payloadSha256: string): Promise<boolean> {
    const result = await this.#pool.query(`INSERT INTO ai.payment_webhook_events (
        payment_provider, external_event_id, event_type, event_created_at, payload, payload_sha256
      ) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (payment_provider, external_event_id) DO NOTHING`,
    [event.provider, event.externalEventId, event.eventType, event.eventCreatedAt, event, payloadSha256]);
    return result.rowCount === 1;
  }

  async claimWebhookEvents(limit: number): Promise<readonly StoredPaymentEvent[]> {
    return this.transaction(async (client) => {
      const result = await client.query<{ id: string; payload: NormalizedPaymentEvent; attempts: number }>(`WITH due AS (
          SELECT id FROM ai.payment_webhook_events
          WHERE (status IN ('received', 'failed') AND available_at <= now())
             OR (status = 'processing' AND locked_at < now() - interval '10 minutes')
          ORDER BY event_created_at, id FOR UPDATE SKIP LOCKED LIMIT $1
        ) UPDATE ai.payment_webhook_events event SET
          status = 'processing', locked_at = now(), attempts = attempts + 1
        FROM due WHERE event.id = due.id RETURNING event.id, event.payload, event.attempts`, [limit]);
      return result.rows.map((row) => ({ id: row.id, event: row.payload, attempt: row.attempts }));
    });
  }

  async processWebhookEvent(stored: StoredPaymentEvent): Promise<void> {
    await this.transaction(async (client) => {
      const lock = await client.query<{ status: string }>("SELECT status FROM ai.payment_webhook_events WHERE id = $1 FOR UPDATE", [stored.id]);
      if (lock.rows[0]?.status !== "processing") return;
      const event = stored.event;
      let finalStatus: "processed" | "ignored" = event.eventType === "ignored" ? "ignored" : "processed";
      switch (event.eventType) {
        case "checkout.completed": await processCheckout(client, event); break;
        case "invoice.paid": await processInvoice(client, event, true); break;
        case "invoice.payment_failed": await processInvoice(client, event, false); break;
        case "subscription.changed": await processSubscription(client, event); break;
        case "payment.refunded": await processRefund(client, event); break;
        case "ignored": finalStatus = "ignored"; break;
      }
      await client.query("UPDATE ai.payment_webhook_events SET status = $2, processed_at = now(), locked_at = NULL, last_error_code = NULL WHERE id = $1", [stored.id, finalStatus]);
    });
  }

  async failWebhookEvent(id: string, errorCode: string, retryAt: Date): Promise<void> {
    await this.#pool.query(`UPDATE ai.payment_webhook_events SET status = 'failed', available_at = $2, locked_at = NULL, last_error_code = $3
      WHERE id = $1 AND status = 'processing'`, [id, retryAt, errorCode.slice(0, 80)]);
  }

  private async transaction<T>(work: (client: PoolClient) => Promise<T>): Promise<T> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const result = await work(client);
      await client.query("COMMIT");
      return result;
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally { client.release(); }
  }
}

interface OrderRow extends QueryResultRow {
  id: string; user_id: number; plan_id: string; payment_provider: string; idempotency_key: string; status: string; external_checkout_id: string | null; external_checkout_url: string | null;
}
const planSelect = `SELECT id, slug, display_name, description, kind, billing_interval, currency,
  amount_minor, credit_amount, entitlements, payment_provider, external_price_ref FROM ai.billing_plans`;
const orderSelect = `SELECT o.id, o.user_id, o.plan_id, o.payment_provider, o.idempotency_key, o.status, o.external_checkout_id, o.external_checkout_url FROM ai.payment_orders o`;

async function processCheckout(client: PoolClient, event: Extract<NormalizedPaymentEvent, { eventType: "checkout.completed" }>): Promise<void> {
  const orderResult = await client.query<{ id: string; user_id: number; plan_id: string; kind: BillingPlan["kind"]; credit_amount: string }>(`SELECT o.id, o.user_id, o.plan_id, p.kind, p.credit_amount
    FROM ai.payment_orders o JOIN ai.billing_plans p ON p.id = o.plan_id
    WHERE o.id = $1 AND o.payment_provider = $2 FOR UPDATE OF o`, [event.data.orderId, event.provider]);
  const order = orderResult.rows[0];
  if (!order) throw codeError("order_not_found");
  if (event.data.customerId) await attachCustomer(client, order.user_id, event.provider, event.data.customerId);
  const isPaid = event.data.paymentStatus === "paid" || event.data.paymentStatus === "no_payment_required";
  await client.query(`UPDATE ai.payment_orders SET
      status = CASE WHEN $2 THEN 'paid'::ai.payment_order_status ELSE status END,
      external_payment_id = COALESCE(external_payment_id, $3),
      external_subscription_id = COALESCE(external_subscription_id, $4),
      external_checkout_url = NULL,
      paid_at = CASE WHEN $2 THEN COALESCE(paid_at, now()) ELSE paid_at END
    WHERE id = $1`, [order.id, isPaid, event.data.paymentId ?? null, event.data.subscriptionId ?? null]);
  if (order.kind === "credit_pack" && isPaid) {
    await grantCredits(client, order.user_id, order.credit_amount, "pack_purchase", "payment_order", order.id, `${event.provider}:checkout:${event.externalEventId}`);
    await client.query("UPDATE ai.payment_orders SET credited_amount = GREATEST(credited_amount, $2) WHERE id = $1", [order.id, order.credit_amount]);
  }
}

async function processInvoice(client: PoolClient, event: Extract<NormalizedPaymentEvent, { eventType: "invoice.paid" | "invoice.payment_failed" }>, paid: boolean): Promise<void> {
  if (!event.data.subscriptionId) return;
  const result = await client.query<{ user_id: number; plan_id: string; credit_amount: string }>(`SELECT o.user_id, o.plan_id, p.credit_amount
    FROM ai.payment_orders o JOIN ai.billing_plans p ON p.id = o.plan_id
    WHERE o.payment_provider = $1 AND o.external_subscription_id = $2 ORDER BY o.created_at DESC LIMIT 1`, [event.provider, event.data.subscriptionId]);
  let owner = result.rows[0];
  if (!owner && event.data.customerId) {
    owner = (await client.query<{ user_id: number; plan_id: string; credit_amount: string }>(`SELECT c.user_id, s.plan_id, p.credit_amount
      FROM ai.billing_customers c JOIN ai.subscriptions s ON s.user_id = c.user_id AND s.payment_provider = c.payment_provider
      JOIN ai.billing_plans p ON p.id = s.plan_id
      WHERE c.payment_provider = $1 AND c.external_customer_id = $2 AND s.external_subscription_id = $3 LIMIT 1`,
    [event.provider, event.data.customerId, event.data.subscriptionId])).rows[0];
  }
  if (!owner) throw codeError("subscription_owner_not_found");
  await client.query(`INSERT INTO ai.subscriptions (user_id, plan_id, payment_provider, external_subscription_id, status, last_provider_event_at)
      VALUES ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (payment_provider, external_subscription_id) DO UPDATE SET
      status = CASE WHEN EXCLUDED.last_provider_event_at >= ai.subscriptions.last_provider_event_at THEN EXCLUDED.status ELSE ai.subscriptions.status END,
      last_provider_event_at = GREATEST(ai.subscriptions.last_provider_event_at, EXCLUDED.last_provider_event_at)`,
  [owner.user_id, owner.plan_id, event.provider, event.data.subscriptionId, paid ? "active" : "past_due", event.eventCreatedAt]);
  if (paid) await grantCredits(client, owner.user_id, owner.credit_amount, "subscription_grant", "invoice", event.data.invoiceId, `${event.provider}:invoice:${event.data.invoiceId}`);
}

async function processSubscription(client: PoolClient, event: Extract<NormalizedPaymentEvent, { eventType: "subscription.changed" }>): Promise<void> {
  let planId: string | undefined;
  if (event.data.externalPriceRef) planId = (await client.query<{ id: string }>(
    "SELECT id FROM ai.billing_plans WHERE payment_provider = $1 AND external_price_ref = $2", [event.provider, event.data.externalPriceRef])).rows[0]?.id;
  const existing = await client.query<{ user_id: number; plan_id: string; last_provider_event_at: Date | string }>(
    "SELECT user_id, plan_id, last_provider_event_at FROM ai.subscriptions WHERE payment_provider = $1 AND external_subscription_id = $2 FOR UPDATE",
  [event.provider, event.data.subscriptionId]);
  if (existing.rows[0] && new Date(existing.rows[0].last_provider_event_at).getTime() > new Date(event.eventCreatedAt).getTime()) return;
  let userId = existing.rows[0]?.user_id;
  planId ??= existing.rows[0]?.plan_id;
  if (!userId && event.data.customerId) userId = (await client.query<{ user_id: number }>(
    "SELECT user_id FROM ai.billing_customers WHERE payment_provider = $1 AND external_customer_id = $2", [event.provider, event.data.customerId])).rows[0]?.user_id;
  if ((!userId || !planId)) {
    const order = (await client.query<{ user_id: number; plan_id: string }>(`SELECT user_id, plan_id FROM ai.payment_orders
      WHERE payment_provider = $1 AND external_subscription_id = $2 ORDER BY created_at DESC LIMIT 1`, [event.provider, event.data.subscriptionId])).rows[0];
    userId ??= order?.user_id; planId ??= order?.plan_id;
  }
  if (!userId || !planId) throw codeError("subscription_mapping_not_found");
  if (event.data.customerId) await attachCustomer(client, userId, event.provider, event.data.customerId);
  await client.query(`INSERT INTO ai.subscriptions (
      user_id, plan_id, payment_provider, external_subscription_id, status, cancel_at_period_end,
      current_period_start, current_period_end, last_provider_event_at
    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
    ON CONFLICT (payment_provider, external_subscription_id) DO UPDATE SET
      plan_id = EXCLUDED.plan_id, status = EXCLUDED.status, cancel_at_period_end = EXCLUDED.cancel_at_period_end,
      current_period_start = EXCLUDED.current_period_start, current_period_end = EXCLUDED.current_period_end,
      last_provider_event_at = EXCLUDED.last_provider_event_at`, [userId, planId, event.provider, event.data.subscriptionId,
    event.data.status, event.data.cancelAtPeriodEnd, event.data.currentPeriodStart ?? null, event.data.currentPeriodEnd ?? null, event.eventCreatedAt]);
}

async function processRefund(client: PoolClient, event: Extract<NormalizedPaymentEvent, { eventType: "payment.refunded" }>): Promise<void> {
  const result = await client.query<{ id: string; user_id: number; amount_minor: string; credited_amount: string; refunded_amount_minor: string; revoked_credit_amount: string }>(`SELECT id, user_id, amount_minor, credited_amount, refunded_amount_minor, revoked_credit_amount
    FROM ai.payment_orders WHERE payment_provider = $1 AND external_payment_id = $2 FOR UPDATE`, [event.provider, event.data.paymentId]);
  const order = result.rows[0];
  if (!order) throw codeError("refunded_order_not_found");
  const total = BigInt(order.amount_minor);
  const cumulativeRefund = BigInt(event.data.refundedAmountMinor);
  if (total <= 0n || cumulativeRefund < 0n || cumulativeRefund > total) throw codeError("invalid_refund_amount");
  const scale = 10_000n;
  const creditedScaled = decimalToScaled(order.credited_amount, scale);
  const targetRevoked = creditedScaled * cumulativeRefund / total;
  const alreadyRevoked = decimalToScaled(order.revoked_credit_amount, scale);
  const delta = targetRevoked - alreadyRevoked;
  if (delta > 0n) await grantCredits(client, order.user_id, scaledToDecimal(-delta, scale), "payment_refund", "payment_order", order.id, `${event.provider}:refund:${event.externalEventId}`);
  await client.query(`UPDATE ai.payment_orders SET refunded_amount_minor = $2, revoked_credit_amount = $3,
      status = CASE WHEN $2 = amount_minor THEN 'refunded'::ai.payment_order_status ELSE 'partially_refunded'::ai.payment_order_status END
    WHERE id = $1`, [order.id, cumulativeRefund.toString(), scaledToDecimal(targetRevoked, scale)]);
}

async function attachCustomer(client: PoolClient, userId: number, provider: string, customerId: string): Promise<void> {
  await client.query(`INSERT INTO ai.billing_customers (user_id, payment_provider, external_customer_id) VALUES ($1, $2, $3)
    ON CONFLICT (user_id, payment_provider) DO UPDATE SET external_customer_id = EXCLUDED.external_customer_id`, [userId, provider, customerId]);
}

async function grantCredits(client: PoolClient, userId: number, amount: string, entryType: string, sourceType: string, sourceRef: string, idempotencyKey: string): Promise<void> {
  if (Number(amount) === 0) return;
  if ((await client.query("SELECT 1 FROM ai.credit_ledger_entries WHERE user_id = $1 AND idempotency_key = $2", [userId, idempotencyKey])).rowCount) return;
  await client.query("INSERT INTO ai.credit_accounts (user_id) VALUES ($1) ON CONFLICT DO NOTHING", [userId]);
  const account = (await client.query<{ available_amount: string; reserved_amount: string }>(`UPDATE ai.credit_accounts SET
      available_amount = available_amount + $2::numeric,
      lifetime_granted = lifetime_granted + GREATEST($2::numeric, 0),
      version = version + 1 WHERE user_id = $1 RETURNING available_amount, reserved_amount`, [userId, amount])).rows[0]!;
  await client.query(`INSERT INTO ai.credit_ledger_entries (
      user_id, entry_type, delta_available, available_after, reserved_after, source_type, source_ref, idempotency_key
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
  [userId, entryType, amount, account.available_amount, account.reserved_amount, sourceType, sourceRef, idempotencyKey]);
}

function mapPlan(row: PlanRow): BillingPlan {
  return { id: row.id, slug: row.slug, displayName: row.display_name, description: row.description, kind: row.kind,
    ...(row.billing_interval ? { billingInterval: row.billing_interval } : {}), currency: row.currency, amountMinor: row.amount_minor,
    creditAmount: row.credit_amount, entitlements: row.entitlements,
    ...(row.payment_provider ? { paymentProvider: row.payment_provider } : {}), ...(row.external_price_ref ? { externalPriceRef: row.external_price_ref } : {}) };
}
function mapOrder(row: OrderRow, plan: BillingPlan): PaymentOrder {
  return { id: row.id, userId: row.user_id, plan, provider: row.payment_provider, idempotencyKey: row.idempotency_key,
    status: row.status, ...(row.external_checkout_id ? { externalCheckoutId: row.external_checkout_id } : {}),
    ...(row.external_checkout_url ? { externalCheckoutUrl: row.external_checkout_url } : {}) };
}
function iso(value: Date | string): string { return new Date(value).toISOString(); }
function codeError(code: string): Error & { code: string } { const error = new Error(code) as Error & { code: string }; error.code = code; return error; }
function decimalToScaled(value: string, scale: bigint): bigint {
  const negative = value.startsWith("-"); const clean = negative ? value.slice(1) : value; const [whole, fraction = ""] = clean.split(".");
  const digits = scale.toString().length - 1; const result = BigInt(whole || "0") * scale + BigInt(fraction.padEnd(digits, "0").slice(0, digits) || "0");
  return negative ? -result : result;
}
function scaledToDecimal(value: bigint, scale: bigint): string {
  const negative = value < 0n; const absolute = negative ? -value : value; const digits = scale.toString().length - 1;
  return `${negative ? "-" : ""}${absolute / scale}.${(absolute % scale).toString().padStart(digits, "0")}`;
}
