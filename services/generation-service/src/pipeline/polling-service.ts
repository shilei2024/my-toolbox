import { ProviderError } from "../providers/errors.ts";
import type { ImageProvider } from "../providers/image-provider.ts";
import type { ProviderCallContext, ProviderStatusResult, ProviderSubmission } from "../providers/types.ts";

export interface PollingOptions { readonly intervalMs: number; readonly maxAttempts: number }
export class PollingService {
  readonly #options: PollingOptions;
  readonly #sleep: (ms: number) => Promise<void>;
  constructor(options: PollingOptions, sleep: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms))) { this.#options = options; this.#sleep = sleep; }
  async wait(provider: ImageProvider, submission: ProviderSubmission, context: ProviderCallContext): Promise<ProviderStatusResult> {
    if (submission.state === "succeeded") return { externalRequestId: submission.externalRequestId, state: "succeeded", outputs: submission.outputs, providerMetadata: submission.providerMetadata, ...(submission.actualCost === undefined ? {} : { actualCost: submission.actualCost }) };
    for (let attempt = 0; attempt < this.#options.maxAttempts; attempt += 1) {
      if (context.signal?.aborted) throw new ProviderError({ providerCode: provider.descriptor.code, category: "cancelled", code: "polling_cancelled", message: "Provider polling was cancelled" });
      if (attempt > 0) await this.#sleep(this.#options.intervalMs);
      const status = await provider.getStatus(submission.externalRequestId, context);
      if (new Set(["succeeded", "failed", "cancelled"]).has(status.state)) return status;
    }
    throw new ProviderError({ providerCode: provider.descriptor.code, category: "timeout", code: "polling_exhausted", message: "Provider polling timed out", retryable: true, externalRequestId: submission.externalRequestId });
  }
}
