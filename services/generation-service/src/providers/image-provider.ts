import type {
  CostEstimate,
  GenerationRequest,
  ProviderBinding,
  ProviderCallContext,
  ProviderCancelResult,
  ProviderDescriptor,
  ProviderHealthResult,
  ProviderStatusResult,
  ProviderSubmission,
} from "./types.ts";

/**
 * The only contract the generation domain may use to execute an image provider.
 * Provider SDK objects and credentials must never cross this boundary.
 */
export interface ImageProvider {
  readonly descriptor: ProviderDescriptor;

  generate(
    request: GenerationRequest,
    binding: ProviderBinding,
    context: ProviderCallContext,
  ): Promise<ProviderSubmission>;

  cancel(
    externalRequestId: string,
    context: ProviderCallContext,
  ): Promise<ProviderCancelResult>;

  getStatus(
    externalRequestId: string,
    context: ProviderCallContext,
  ): Promise<ProviderStatusResult>;

  healthCheck(context: ProviderCallContext): Promise<ProviderHealthResult>;

  estimateCost(request: GenerationRequest, binding: ProviderBinding): Promise<CostEstimate>;
}

