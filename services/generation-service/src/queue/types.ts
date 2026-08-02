import type { GenerationRequest, ProviderBinding, ProviderCallContext } from "../providers/types.ts";
import type { ProductionGenerationResult } from "../pipeline/production-generation-pipeline.ts";

export const GENERATION_QUEUE_JOB_NAME = "generate" as const;
export const QUEUE_SCHEMA_VERSION = 1 as const;

export interface GenerationQueueJobData {
  readonly schemaVersion: typeof QUEUE_SCHEMA_VERSION;
  readonly jobId: string;
  readonly requestId: string;
  readonly enqueuedAt: string;
}

export interface GenerationQueueResult {
  readonly jobId: string;
  readonly state: "completed";
  readonly providerCode?: string;
  readonly assetUrls: readonly string[];
}

export type GenerationQueuePublicState = "waiting" | "delayed" | "running" | "completed" | "failed" | "cancelled" | "unknown";

export interface GenerationQueueStatus {
  readonly jobId: string;
  readonly state: GenerationQueuePublicState;
  readonly progress: number | Record<string, unknown>;
  readonly attemptsMade: number;
  readonly failedReason?: string;
}

export interface GenerationExecutionPlan {
  readonly request: GenerationRequest;
  readonly bindings: readonly ProviderBinding[];
  readonly context: ProviderCallContext;
}

export type GenerationJobClaim =
  | { readonly kind: "execute"; readonly plan: GenerationExecutionPlan }
  | { readonly kind: "completed"; readonly assetUrls: readonly string[]; readonly providerCode?: string }
  | { readonly kind: "cancelled" };

export interface QueueAttemptDescriptor {
  readonly queueJobId: string;
  readonly attemptNumber: number;
}

export interface SafeQueueFailure {
  readonly category: string;
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
}

export interface GenerationJobRepository {
  claim(jobId: string, descriptor: QueueAttemptDescriptor): Promise<GenerationJobClaim>;
  markCompleted(jobId: string, attemptId: string, result: ProductionGenerationResult): Promise<void>;
  markFailed(jobId: string, attemptId: string, failure: SafeQueueFailure, willRetry: boolean): Promise<void>;
  markCancelled(jobId: string, attemptId: string, reason: string): Promise<void>;
}

export function parseGenerationQueueJobData(value: unknown): GenerationQueueJobData {
  if (!isObject(value) || value.schemaVersion !== QUEUE_SCHEMA_VERSION || !isIdentifier(value.jobId) || !isIdentifier(value.requestId) || typeof value.enqueuedAt !== "string" || !Number.isFinite(Date.parse(value.enqueuedAt))) {
    throw new QueuePayloadError("Queue payload does not match schema version 1");
  }
  const allowed = new Set(["schemaVersion", "jobId", "requestId", "enqueuedAt"]);
  if (Object.keys(value).some((key) => !allowed.has(key))) throw new QueuePayloadError("Queue payload contains unsupported fields");
  return { schemaVersion: QUEUE_SCHEMA_VERSION, jobId: value.jobId, requestId: value.requestId, enqueuedAt: value.enqueuedAt };
}

export class QueuePayloadError extends Error {
  constructor(message: string) { super(message); this.name = "QueuePayloadError"; }
}

function isObject(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function isIdentifier(value: unknown): value is string { return typeof value === "string" && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(value); }

