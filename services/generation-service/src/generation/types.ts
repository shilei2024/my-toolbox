import type { JsonObject } from "../providers/types.ts";

export type GenerationStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type GenerationVisibility = "public" | "private";
export type PromptVisibility = "public" | "hidden";

export interface GenerationWorkflowView {
  readonly slug: string;
  readonly name: string;
  readonly description: string;
  readonly category: string;
  readonly defaults: {
    readonly width: number;
    readonly height: number;
    readonly count: number;
    readonly visibility: GenerationVisibility;
  };
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
}

export interface GenerationView {
  readonly id: string;
  readonly status: GenerationStatus;
  readonly workflowSlug: string;
  readonly workflowName: string;
  readonly width: number;
  readonly height: number;
  readonly count: number;
  readonly visibility: GenerationVisibility;
  readonly promptVisibility: PromptVisibility;
  readonly creditsReserved: string;
  readonly creditsCharged: string;
  readonly cancelRequested: boolean;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly finishedAt?: string;
  readonly error?: { readonly code: string; readonly message: string };
  readonly images: readonly { readonly id: string; readonly slug: string }[];
}

export interface CancelGenerationResult {
  readonly generation: GenerationView;
  readonly accepted: boolean;
  readonly signalWorker: boolean;
}
