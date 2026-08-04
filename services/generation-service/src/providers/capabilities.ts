import { ProviderError } from "./errors.ts";
import type { GenerationRequest, ProviderDescriptor } from "./types.ts";

export function supportsRequest(descriptor: ProviderDescriptor, request: GenerationRequest): boolean {
  const capability = descriptor.capabilities;
  return (
    descriptor.availability !== "disabled" &&
    capability.modes.includes(request.mode) &&
    (capability.workflowKinds.length === 0 || capability.workflowKinds.includes(request.workflow.kind)) &&
    request.width >= capability.minWidth &&
    request.width <= capability.maxWidth &&
    request.height >= capability.minHeight &&
    request.height <= capability.maxHeight &&
    request.count >= 1 &&
    request.count <= capability.maxOutputs &&
    (request.seed === undefined || capability.supportsSeed)
  );
}

export function assertRequestSupported(descriptor: ProviderDescriptor, request: GenerationRequest): void {
  if (!supportsRequest(descriptor, request)) {
    throw new ProviderError({
      providerCode: descriptor.code,
      category: "unsupported",
      code: "unsupported_request",
      message: `Provider ${descriptor.code} does not support the requested capabilities`,
      retryable: false,
    });
  }
}

