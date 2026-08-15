import type { JsonObject } from "../providers/types.ts";
import type { CreditTier, MediaType } from "../providers/types.ts";

export type GenerationStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type GenerationVisibility = "public" | "private";
export type PromptVisibility = "public" | "hidden";
export type GenerationMode = "workflow" | "api";
export type DefaultModerationStatus = "pending" | "approved";

export function parseDefaultModeration(value: string | undefined, fallback: DefaultModerationStatus = "pending"): DefaultModerationStatus {
  const normalized = value?.trim().toLowerCase();
  if (!normalized) return fallback;
  if (normalized !== "pending" && normalized !== "approved") throw new Error("GALLERY_DEFAULT_MODERATION must be 'pending' or 'approved'");
  return normalized;
}

export interface GenerationWorkflowView {
  readonly slug: string;
  readonly name: string;
  readonly description: string;
  readonly category: string;
  readonly mode: GenerationMode;
  readonly mediaType: MediaType;
  readonly defaults: {
    readonly width: number;
    readonly height: number;
    readonly count: number;
    readonly visibility: GenerationVisibility;
    readonly promptVisibility: PromptVisibility;
    readonly durationSeconds?: number;
    /** 同族工作流的模式元数据（如 MiniMax H3 三合一）：驱动前端模式页签与参考图上传入口。 */
    readonly modeMeta?: { readonly key: string; readonly label: string; readonly maxImages: number };
    /** 工作流允许的分辨率档位（来自迁移 0021 等）：驱动前端分辨率下拉且服务端 create 校验同源。 */
    readonly videoResolutions?: readonly { readonly key: string; readonly label: string; readonly height: number }[];
  };
  readonly countRange: { readonly min: number; readonly max: number };
  readonly sizes: readonly { readonly width: number; readonly height: number }[];
  readonly durations: readonly number[];
  readonly creditCost: string;
}

export interface CreateGenerationInput {
  readonly userId: number;
  readonly requestId: string;
  readonly idempotencyKey: string;
  readonly workflowSlug: string;
  readonly prompt: string;
  readonly negativePrompt: string;
  readonly width: number;
  readonly height: number;
  readonly count: number;
  readonly visibility: GenerationVisibility;
  readonly promptVisibility: PromptVisibility;
  readonly parameters: Readonly<JsonObject>;
  readonly creditTier: CreditTier;
}

export interface GenerationView {
  readonly id: string;
  readonly status: GenerationStatus;
  readonly workflowSlug: string;
  readonly workflowName: string;
  readonly mode: GenerationMode;
  readonly mediaType: MediaType;
  readonly prompt: string;
  readonly negativePrompt: string;
  readonly width: number;
  readonly height: number;
  readonly count: number;
  readonly visibility: GenerationVisibility;
  readonly promptVisibility: PromptVisibility;
  readonly creditsReserved: string;
  readonly creditsCharged: string;
  readonly creditTier: CreditTier;
  readonly cancelRequested: boolean;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly finishedAt?: string;
  readonly error?: { readonly code: string; readonly message: string };
  readonly images: readonly { readonly id: string; readonly slug: string }[];
  readonly outputs: readonly GenerationOutputView[];
}

export interface GenerationOutputView {
  readonly id: string;
  readonly mediaType: MediaType;
  readonly url: string;
  readonly mimeType: string;
  readonly width: number;
  readonly height: number;
  readonly durationSeconds?: number;
}

export interface GenerationListRequest {
  readonly cursor?: string;
  readonly limit?: number;
  readonly status?: GenerationStatus;
}

export interface GenerationPageResult {
  readonly items: readonly GenerationView[];
  readonly next?: { readonly at: string; readonly id: string };
}

export interface GenerationPage {
  readonly items: readonly GenerationView[];
  readonly nextCursor?: string;
}

export interface CancelGenerationResult {
  readonly generation: GenerationView;
  readonly accepted: boolean;
  readonly signalWorker: boolean;
}
