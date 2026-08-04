import type { NormalizedPaymentEvent, PaymentOrder } from "./types.ts";

export interface CheckoutSessionResult {
  readonly externalSessionId: string;
  readonly url: string;
  readonly expiresAt?: string;
}

export interface PaymentProvider {
  readonly code: string;
  createCheckout(input: {
    readonly order: PaymentOrder;
    readonly externalCustomerId?: string;
    readonly successUrl: string;
    readonly cancelUrl: string;
  }): Promise<CheckoutSessionResult>;
  createCustomerPortal(input: { readonly externalCustomerId: string; readonly returnUrl: string }): Promise<{ readonly url: string }>;
  verifyAndNormalizeWebhook(rawBody: Buffer, signature: string): NormalizedPaymentEvent;
}

export class PaymentProviderRegistry {
  readonly #providers = new Map<string, PaymentProvider>();

  register(provider: PaymentProvider): void {
    if (this.#providers.has(provider.code)) throw new Error(`Duplicate payment provider: ${provider.code}`);
    this.#providers.set(provider.code, provider);
  }

  get(code: string): PaymentProvider | undefined {
    return this.#providers.get(code);
  }
}

