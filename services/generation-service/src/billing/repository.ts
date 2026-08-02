import type { BillingSummary, NormalizedPaymentEvent, PaymentOrder, StoredPaymentEvent } from "./types.ts";

export interface BillingRepository {
  summary(userId?: number): Promise<BillingSummary>;
  createOrGetOrder(userId: number, planSlug: string, idempotencyKey: string): Promise<PaymentOrder>;
  customerReference(userId: number, provider: string): Promise<string | undefined>;
  markCheckoutOpen(orderId: string, externalCheckoutId: string, checkoutUrl: string, expiresAt?: string): Promise<void>;
  recordWebhook(event: NormalizedPaymentEvent, payloadSha256: string): Promise<boolean>;
  claimWebhookEvents(limit: number): Promise<readonly StoredPaymentEvent[]>;
  processWebhookEvent(event: StoredPaymentEvent): Promise<void>;
  failWebhookEvent(id: string, errorCode: string, retryAt: Date): Promise<void>;
}
