import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import type { PostgresProviderCatalog } from "./postgres-catalog.ts";
import type { ProviderRegistry } from "./registry.ts";

export interface ProviderHealthMonitorOptions {
  readonly failureThreshold: number;
}

/**
 * Executes low-frequency, provider-local health checks and persists routing
 * state. PostgreSQL remains the source of truth so several worker replicas
 * converge through the catalog rather than relying on local process memory.
 */
export class ProviderHealthMonitor {
  readonly #catalog: PostgresProviderCatalog;
  readonly #registry: ProviderRegistry;
  readonly #logger: StructuredLogger;
  readonly #failureThreshold: number;

  constructor(catalog: PostgresProviderCatalog, registry: ProviderRegistry, logger: StructuredLogger, options: ProviderHealthMonitorOptions) {
    if (!Number.isSafeInteger(options.failureThreshold) || options.failureThreshold < 1) throw new TypeError("failureThreshold must be a positive integer");
    this.#catalog = catalog;
    this.#registry = registry;
    this.#logger = logger;
    this.#failureThreshold = options.failureThreshold;
  }

  async runOnce(): Promise<void> {
    for (const provider of this.#registry.list()) {
      let healthy = false;
      let latencyMs = 0;
      try {
        const result = await provider.healthCheck({ requestId: `provider-health-${Date.now()}`, attemptId: `provider-health-${provider.descriptor.code}` });
        healthy = result.healthy;
        latencyMs = Math.max(0, Math.round(result.latencyMs));
      } catch {
        // An adapter must not be able to take down the worker merely because
        // its health endpoint is unavailable.
      }
      await this.#catalog.recordHealth(provider.descriptor.code, healthy, this.#failureThreshold);
      this.#logger.info("provider.health_checked", { providerCode: provider.descriptor.code, healthy, latencyMs });
    }
    await this.#catalog.refreshRegistry(this.#registry);
  }
}
