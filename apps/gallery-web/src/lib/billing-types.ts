/**
 * Billing 前端共享类型（镜像 Generation Service 的账单契约）。
 */

export type BillingPlanKind = "free" | "subscription" | "pack";
export type BillingInterval = "month" | "year";

export interface BillingPlan {
  readonly id: string;
  readonly slug: string;
  readonly displayName: string;
  readonly description: string;
  readonly kind: BillingPlanKind;
  readonly currency: string;
  /** 金额，单位：分（minor unit）。 */
  readonly amountMinor: string;
  /** 附赠/包含的积分，字符串十进制（如 "0.0000"）。 */
  readonly creditAmount: string;
  readonly billingInterval?: BillingInterval;
  readonly entitlements: {
    readonly private_generation?: boolean;
    readonly priority_queue?: boolean;
    readonly [key: string]: boolean | undefined;
  };
}

export interface BillingAccount {
  readonly availableAmount: string;
  readonly reservedAmount: string;
  readonly lifetimeGranted: string;
  readonly lifetimeSpent: string;
}

export interface BillingSubscription {
  readonly planName: string;
  readonly status: string;
  readonly cancelAtPeriodEnd: boolean;
  readonly currentPeriodEnd?: string;
}

export interface CreditLedgerEntry {
  readonly id: string;
  readonly entryType: string;
  readonly createdAt: string;
  readonly deltaAvailable: string;
}

export interface BillingSummary {
  readonly plans: readonly BillingPlan[];
  readonly account?: BillingAccount;
  readonly subscription?: BillingSubscription;
  readonly ledger: readonly CreditLedgerEntry[];
}
