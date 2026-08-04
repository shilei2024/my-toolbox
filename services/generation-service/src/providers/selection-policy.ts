import { NoEligibleProviderError } from "./errors.ts";
import { supportsRequest } from "./capabilities.ts";
import type { ImageProvider } from "./image-provider.ts";
import type { GenerationRequest, ProviderBinding } from "./types.ts";
import type { ProviderRegistry } from "./registry.ts";

export interface ProviderCandidate {
  readonly provider: ImageProvider;
  readonly binding: ProviderBinding;
}

export class ProviderSelectionPolicy {
  readonly #registry: ProviderRegistry;

  constructor(registry: ProviderRegistry) {
    this.#registry = registry;
  }

  rank(request: GenerationRequest, bindings: readonly ProviderBinding[]): readonly ProviderCandidate[] {
    const candidates = bindings
      .filter((binding) => binding.enabled && binding.workflowVersionId === request.workflow.workflowVersionId)
      .filter((binding) => this.#registry.has(binding.providerCode))
      .map((binding) => ({ provider: this.#registry.get(binding.providerCode), binding }))
      .filter(({ provider }) => {
        const routing = this.#registry.routing(provider.descriptor.code);
        return supportsRequest({ ...provider.descriptor, availability: routing.availability }, request);
      });

    candidates.sort((left, right) => {
      const leftRouting = this.#registry.routing(left.provider.descriptor.code);
      const rightRouting = this.#registry.routing(right.provider.descriptor.code);
      const availability = availabilityRank(leftRouting.availability) - availabilityRank(rightRouting.availability);
      if (availability !== 0) return availability;
      if (left.binding.priority !== right.binding.priority) return left.binding.priority - right.binding.priority;
      if (leftRouting.priority !== rightRouting.priority) {
        return leftRouting.priority - rightRouting.priority;
      }
      const leftCost = left.binding.estimatedCost ?? Number.POSITIVE_INFINITY;
      const rightCost = right.binding.estimatedCost ?? Number.POSITIVE_INFINITY;
      if (leftCost !== rightCost) return leftCost - rightCost;
      return left.provider.descriptor.code.localeCompare(right.provider.descriptor.code);
    });
    return candidates;
  }

  select(request: GenerationRequest, bindings: readonly ProviderBinding[]): ProviderCandidate {
    const candidate = this.rank(request, bindings)[0];
    if (!candidate) {
      throw new NoEligibleProviderError();
    }
    return candidate;
  }
}

function availabilityRank(availability: "active" | "degraded" | "disabled"): number {
  if (availability === "active") return 0;
  if (availability === "degraded") return 1;
  return 2;
}
