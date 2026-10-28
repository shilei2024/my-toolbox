export const PROVIDER_AVAILABILITIES = ["active", "degraded", "disabled"] as const;
export type ProviderAvailability = (typeof PROVIDER_AVAILABILITIES)[number];
export type CreditTier = "free" | "member";

export const MEDIA_TYPES = ["image", "video"] as const;
export type MediaType = (typeof MEDIA_TYPES)[number];

export const GENERATION_MODES = ["text-to-image", "image-to-image", "text-to-video", "image-to-video"] as const;
export type GenerationMode = (typeof GENERATION_MODES)[number];

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface ProviderCapabilities {
  /** Omitted only by legacy test doubles; production adapters declare this explicitly. */
  readonly mediaTypes?: readonly MediaType[];
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
  /** Legacy callers default to image; durable jobs always set this explicitly. */
  readonly mediaType?: MediaType;
  readonly mode: GenerationMode;
  readonly prompt: string;
  readonly negativePrompt: string;
  /** Sanitized owner name used to organize COS objects (e.g. email local part). */
  readonly ownerKey?: string;
  /** Credit tier the job was created under; free-tier jobs can only use free models. */
  readonly creditTier?: CreditTier;
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
  readonly modelTier?: CreditTier;
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
  /**
   * Durable task metadata derived from the generation request. Providers that
   * poll an external asynchronous job (ComfyUI / Ark video) keep a richer
   * per-task context in memory; after a worker restart that memory is gone,
   * and this fallback lets getStatus() keep serving the task instead of
   * failing it (and refunding credits) while the upstream job still runs.
   */
  readonly taskMetadata?: {
    readonly mediaType?: MediaType;
    readonly width?: number;
    readonly height?: number;
    readonly durationSeconds?: number;
  };
}

interface OutputBase {
  readonly mimeType: string;
  readonly width: number;
  readonly height: number;
  readonly seed?: number;
}

export type ProviderImageOutput =
  | (OutputBase & { readonly mediaType?: "image"; readonly kind: "base64"; readonly data: string })
  | (OutputBase & { readonly mediaType?: "image"; readonly kind: "remote-url"; readonly url: string })
  | (OutputBase & { readonly mediaType?: "image"; readonly kind: "local-file"; readonly path: string });

interface VideoOutputBase extends OutputBase {
  readonly mediaType: "video";
  readonly durationSeconds: number;
}

export type ProviderVideoOutput =
  | (VideoOutputBase & { readonly kind: "base64"; readonly data: string })
  | (VideoOutputBase & { readonly kind: "remote-url"; readonly url: string })
  | (VideoOutputBase & { readonly kind: "local-file"; readonly path: string });

export type ProviderOutput = ProviderImageOutput | ProviderVideoOutput;

export type ProviderTaskState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface ProviderSubmission {
  readonly externalRequestId: string;
  readonly state: "queued" | "running" | "succeeded";
  readonly outputs: readonly ProviderOutput[];
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
  readonly outputs: readonly ProviderOutput[];
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
