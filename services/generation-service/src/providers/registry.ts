import type { ImageProvider } from "./image-provider.ts";
import type { ProviderAvailability } from "./types.ts";

export interface ProviderRoutingState {
  readonly availability: ProviderAvailability;
  readonly priority: number;
}

export class ProviderRegistry {
  readonly #providers = new Map<string, ImageProvider>();
  readonly #routing = new Map<string, ProviderRoutingState>();

  register(provider: ImageProvider): void {
    const code = provider.descriptor.code.trim();
    if (!code) {
      throw new TypeError("Provider code cannot be empty");
    }
    if (this.#providers.has(code)) {
      throw new Error(`Provider ${code} is already registered`);
    }
    this.#providers.set(code, provider);
  }

  unregister(code: string): boolean {
    this.#routing.delete(code);
    return this.#providers.delete(code);
  }

  has(code: string): boolean {
    return this.#providers.has(code);
  }

  get(code: string): ImageProvider {
    const provider = this.#providers.get(code);
    if (!provider) {
      throw new Error(`Provider ${code} is not registered`);
    }
    return provider;
  }

  list(): readonly ImageProvider[] {
    return [...this.#providers.values()];
  }

  setRouting(code: string, state: ProviderRoutingState): void {
    if (!this.#providers.has(code)) throw new Error(`Provider ${code} is not registered`);
    if (!Number.isInteger(state.priority) || state.priority < 0) throw new TypeError("Provider priority must be a non-negative integer");
    this.#routing.set(code, { availability: state.availability, priority: state.priority });
  }

  routing(code: string): ProviderRoutingState {
    const provider = this.get(code);
    return this.#routing.get(code) ?? { availability: provider.descriptor.availability, priority: provider.descriptor.priority };
  }
}
