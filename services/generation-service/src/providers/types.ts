export const PROVIDER_AVAILABILITIES = ["active", "degraded", "disabled"] as const;
export type ProviderAvailability = (typeof PROVIDER_AVAILABILITIES)[number];

export const GENERATION_MODES = ["text-to-image", "image-to-image"] as const;
export type GenerationMode = (typeof GENERATION_MODES)[number];

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface ProviderCapabilities {
  readonly modes: readonly GenerationMode[];
  readonly workflowKinds: readonly string[];
  readonly models: readonly string[];
  readonly minWidth: number;
  readonly maxWidth: number;
  readonly minHeight: number;
  readonly maxHeight: number;
  readonly maxOutputs: number;
  readonly supportsSeed: boolean;
  readonly supportsCancellation: boolean;
  readonly supportsStatusPolling: boolean;
}

export interface ProviderDescriptor {
  readonly code: string;
  readonly displayName: string;
  readonly availability: ProviderAvailability;
  readonly priority: number;
  readonly capabilities: ProviderCapabilities;
}

export interface WorkflowReference {
  readonly workflowId: string;
  readonly workflowVersionId: string;
  readonly version: number;
  readonly kind: string;
}

export interface ImageInput {
  readonly url: string;
  readonly mimeType: string;
}

export interface GenerationRequest {
  readonly jobId: string;
  readonly workflow: WorkflowReference;
  readonly mode: GenerationMode;
  readonly prompt: string;
  readonly negativePrompt: string;
  readonly width: number;
  readonly height: number;
  readonly count: number;
  readonly seed?: number;
  readonly inputImages?: readonly ImageInput[];
  readonly parameters: Readonly<JsonObject>;
}

export interface ProviderBinding {
  readonly id: string;
  readonly providerCode: string;
  readonly workflowVersionId: string;
  readonly providerWorkflowRef?: string;
  readonly providerModel?: string;
  readonly providerConfig: Readonly<JsonObject>;
  readonly priority: number;
  readonly estimatedCost?: number;
  readonly timeoutSeconds: number;
  readonly maxAttempts: number;
  readonly enabled: boolean;
}

export interface ProviderCallContext {
  readonly requestId: string;
  readonly attemptId: string;
  readonly deadlineAt?: Date;
  readonly signal?: AbortSignal;
}

interface OutputBase {
  readonly mimeType: string;
  readonly width: number;
  readonly height: number;
  readonly seed?: number;
}

export type ProviderImageOutput =
  | (OutputBase & { readonly kind: "base64"; readonly data: string })
  | (OutputBase & { readonly kind: "remote-url"; readonly url: string })
  | (OutputBase & { readonly kind: "local-file"; readonly path: string });

export type ProviderTaskState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface ProviderSubmission {
  readonly externalRequestId: string;
  readonly state: "queued" | "running" | "succeeded";
  readonly outputs: readonly ProviderImageOutput[];
  readonly providerMetadata: Readonly<JsonObject>;
  readonly actualCost?: number;
}

export interface ProviderFailure {
  readonly category: string;
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly externalRequestId?: string;
  readonly statusCode?: number;
}

export interface ProviderStatusResult {
  readonly externalRequestId: string;
  readonly state: ProviderTaskState;
  readonly progress?: number;
  readonly outputs: readonly ProviderImageOutput[];
  readonly error?: ProviderFailure;
  readonly providerMetadata: Readonly<JsonObject>;
  readonly actualCost?: number;
}

export interface ProviderCancelResult {
  readonly externalRequestId: string;
  readonly accepted: boolean;
  readonly state: ProviderTaskState;
}

export interface ProviderHealthResult {
  readonly healthy: boolean;
  readonly latencyMs: number;
  readonly checkedAt: Date;
  readonly message?: string;
}

export interface CostEstimate {
  readonly amount: number;
  readonly currency: string;
  readonly estimated: true;
}
