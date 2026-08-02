export interface BillingConfig {
  readonly publicBaseUrl: string;
  readonly webhookHost: string;
  readonly webhookPort: number;
  readonly stripe?: { readonly secretKey: string; readonly webhookSecret: string };
}

export function loadBillingConfig(env: NodeJS.ProcessEnv = process.env): BillingConfig {
  const enabled = env.BILLING_STRIPE_ENABLED === "true";
  const secretKey = env.STRIPE_SECRET_KEY?.trim();
  const webhookSecret = env.STRIPE_WEBHOOK_SECRET?.trim();
  if (enabled && (!secretKey || !webhookSecret)) throw new Error("STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are required when BILLING_STRIPE_ENABLED=true");
  return {
    publicBaseUrl: validBaseUrl(env.BILLING_PUBLIC_BASE_URL ?? "http://localhost:3000"),
    webhookHost: env.BILLING_WEBHOOK_HOST ?? "127.0.0.1",
    webhookPort: integer(env.BILLING_WEBHOOK_PORT, 8091, 1, 65535),
    ...(enabled ? { stripe: { secretKey: secretKey!, webhookSecret: webhookSecret! } } : {}),
  };
}

function validBaseUrl(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) throw new Error("BILLING_PUBLIC_BASE_URL must be HTTPS outside local development");
  return url.toString().replace(/\/$/, "");
}
function integer(value: string | undefined, fallback: number, min: number, max: number): number {
  if (!value) return fallback; const result = Number(value); if (!Number.isInteger(result) || result < min || result > max) throw new Error("Invalid billing integer setting"); return result;
}

