export type BillingPlanKind = "free" | "subscription" | "credit_pack";
export type SubscriptionStatus = "incomplete" | "trialing" | "active" | "past_due" | "paused" | "cancelled" | "unpaid";

export interface BillingPlan {
  readonly id: string;
  readonly slug: string;
  readonly displayName: string;
  readonly description: string;
  readonly kind: BillingPlanKind;
  readonly billingInterval?: "month" | "year";
  readonly currency: string;
  readonly amountMinor: string;
  readonly creditAmount: string;
  readonly entitlements: Readonly<Record<string, unknown>>;
  readonly paymentProvider?: string;
  readonly externalPriceRef?: string;
}

export interface CreditAccountView {
  readonly availableAmount: string;
  readonly reservedAmount: string;
  readonly lifetimeGranted: string;
  readonly lifetimeSpent: string;
}

export interface CreditLedgerEntryView {
  readonly id: string;
  readonly entryType: string;
  readonly deltaAvailable: string;
  readonly deltaReserved: string;
  readonly sourceType: string;
  readonly sourceRef: string;
  readonly createdAt: string;
}

export interface SubscriptionView {
  readonly planSlug: string;
  readonly planName: string;
  readonly provider: string;
  readonly status: SubscriptionStatus;
  readonly cancelAtPeriodEnd: boolean;
  readonly currentPeriodEnd?: string;
}

export interface BillingSummary {
  readonly plans: readonly BillingPlan[];
  readonly account?: CreditAccountView;
  readonly subscription?: SubscriptionView;
  readonly ledger: readonly CreditLedgerEntryView[];
}

export interface PaymentOrder {
  readonly id: string;
  readonly userId: number;
  readonly plan: BillingPlan;
  readonly provider: string;
  readonly idempotencyKey: string;
  readonly status: string;
  readonly externalCheckoutId?: string;
  readonly externalCheckoutUrl?: string;
}

export type NormalizedPaymentEvent =
  | PaymentEventBase<"checkout.completed", {
      readonly orderId: string;
      readonly customerId?: string;
      readonly subscriptionId?: string;
      readonly paymentId?: string;
      readonly paymentStatus: string;
      readonly mode: "payment" | "subscription" | "setup";
    }>
  | PaymentEventBase<"invoice.paid" | "invoice.payment_failed", {
      readonly invoiceId: string;
      readonly customerId?: string;
      readonly subscriptionId?: string;
    }>
  | PaymentEventBase<"subscription.changed", {
      readonly customerId?: string;
      readonly subscriptionId: string;
      readonly externalPriceRef?: string;
      readonly status: SubscriptionStatus;
      readonly cancelAtPeriodEnd: boolean;
      readonly currentPeriodStart?: string;
      readonly currentPeriodEnd?: string;
    }>
  | PaymentEventBase<"payment.refunded", {
      readonly paymentId: string;
      readonly amountMinor: string;
      readonly refundedAmountMinor: string;
    }>
  | PaymentEventBase<"ignored", { readonly originalType: string }>;

interface PaymentEventBase<TType extends string, TData> {
  readonly provider: string;
  readonly externalEventId: string;
  readonly eventType: TType;
  readonly eventCreatedAt: string;
  readonly data: TData;
}

export interface StoredPaymentEvent {
  readonly id: string;
  readonly event: NormalizedPaymentEvent;
  readonly attempt: number;
}
