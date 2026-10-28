import { ProviderError } from "../providers/errors.ts";
import type { ImageProvider } from "../providers/image-provider.ts";
import type { ProviderCallContext, ProviderStatusResult, ProviderSubmission } from "../providers/types.ts";

export interface PollingOptions { readonly intervalMs: number; readonly maxAttempts: number }

/**
 * 长任务轮询的间隔自适应参数：
 * - 前 `ESCALATION_SLICE` 次按配置间隔轮询（默认 1s，覆盖短任务）；
 * - 之后每 `ESCALATION_SLICE` 次间隔翻倍，封顶 `MAX_INTERVAL_MS`，
 *   避免 2 小时级视频任务以 1s 频率打爆 Provider（7200 次请求 → 数百次）。
 */
const ESCALATION_SLICE = 60;
const MAX_INTERVAL_MS = 30_000;

export class PollingService {
  readonly #options: PollingOptions;
  readonly #sleep: (ms: number) => Promise<void>;
  constructor(options: PollingOptions, sleep: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms))) { this.#options = options; this.#sleep = sleep; }

  /**
   * 轮询 Provider 直至终态。
   *
   * 关键契约：
   * 1. `timeoutMs`（来自 binding 的 `timeoutSeconds`）提供时以 deadline 为准，
   *    `maxAttempts` 不再截断轮询——否则 10 分钟的默认尝试预算会先于 2 小时的
   *    deadline 耗尽，抛出可重试超时后队列重新提交任务，导致同一任务在
   *    Provider 侧被重复执行多次。
   * 2. 超时错误的 `retryable` 始终取调用方传入的 `timeoutRetryable`
   *    （binding 的 `retryOnTimeout`），任何路径都不允许硬编码。
   */
  async wait(provider: ImageProvider, submission: ProviderSubmission, context: ProviderCallContext, timeoutMs?: number, timeoutRetryable = true): Promise<ProviderStatusResult> {
    if (submission.state === "succeeded") return { externalRequestId: submission.externalRequestId, state: "succeeded", outputs: submission.outputs, providerMetadata: submission.providerMetadata, ...(submission.actualCost === undefined ? {} : { actualCost: submission.actualCost }) };
    const deadline = timeoutMs !== undefined && timeoutMs > 0 ? Date.now() + timeoutMs : undefined;
    for (let attempt = 0; ; attempt += 1) {
      if (deadline !== undefined ? Date.now() >= deadline : attempt >= this.#options.maxAttempts) {
        throw new ProviderError({ providerCode: provider.descriptor.code, category: "timeout", code: "polling_exhausted", message: "Provider polling timed out", retryable: timeoutRetryable, externalRequestId: submission.externalRequestId });
      }
      if (context.signal?.aborted) throw new ProviderError({ providerCode: provider.descriptor.code, category: "cancelled", code: "polling_cancelled", message: "Provider polling was cancelled" });
      if (attempt > 0) await this.#sleep(this.#intervalFor(attempt));
      const status = await provider.getStatus(submission.externalRequestId, context);
      if (new Set(["succeeded", "failed", "cancelled"]).has(status.state)) return status;
    }
  }

  /** 依据已轮询次数计算下一次等待间隔：基础间隔 → 每 60 次翻倍 → 30s 封顶。 */
  #intervalFor(attempt: number): number {
    return Math.min(this.#options.intervalMs * 2 ** Math.floor(attempt / ESCALATION_SLICE), MAX_INTERVAL_MS);
  }
}
