import { ProviderError } from "../providers/errors.ts";
import type { CostEstimate, ProviderBinding, ProviderCallContext, ProviderCancelResult, ProviderStatusResult } from "../providers/types.ts";

export function synchronousCancellation(externalRequestId: string): ProviderCancelResult {
  return { externalRequestId, accepted: false, state: "failed" };
}

export function synchronousStatus(providerCode: string, externalRequestId: string): ProviderStatusResult {
  return {
    externalRequestId,
    state: "failed",
    outputs: [],
    providerMetadata: {},
    error: { category: "unsupported", code: "status_polling_unsupported", message: `${providerCode} uses synchronous image generation`, retryable: false, externalRequestId },
  };
}

export function bindingCost(binding: ProviderBinding): CostEstimate {
  return { amount: binding.estimatedCost ?? 0, currency: "USD", estimated: true };
}

export function modelFrom(binding: ProviderBinding, providerCode: string): string {
  const model = binding.providerModel?.trim();
  if (!model || !/^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(model)) {
    throw new ProviderError({ providerCode, category: "configuration", code: "provider_model_missing", message: "Provider model binding is missing or invalid", retryable: false });
  }
  return model;
}

export function callSignal(context: ProviderCallContext): AbortSignal | undefined { return context.signal; }

export function configString(binding: ProviderBinding, key: string): string | undefined {
  const value = binding.providerConfig[key];
  return typeof value === "string" ? value : undefined;
}

export function configBoolean(binding: ProviderBinding, key: string): boolean | undefined {
  const value = binding.providerConfig[key];
  return typeof value === "boolean" ? value : undefined;
}

export function configNumber(binding: ProviderBinding, key: string): number | undefined {
  const value = binding.providerConfig[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
