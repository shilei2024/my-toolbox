export type GenerationStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type GenerationVisibility = "public" | "private";
export type GenerationMode = "workflow" | "api";
export type GenerationMediaType = "image" | "video";

export interface GenerationWorkflow {
  readonly slug: string;
  readonly name: string;
  readonly description: string;
  readonly category: string;
  readonly mode: GenerationMode;
  readonly mediaType: GenerationMediaType;
  readonly defaults: { readonly width: number; readonly height: number; readonly count: number; readonly visibility: GenerationVisibility; readonly promptVisibility: "public" | "hidden"; readonly durationSeconds?: number };
  readonly countRange: { readonly min: number; readonly max: number };
  readonly sizes: readonly { readonly width: number; readonly height: number }[];
  readonly durations: readonly number[];
  readonly creditCost: string;
}

export interface GenerationView {
  readonly id: string;
  readonly status: GenerationStatus;
  readonly workflowSlug: string;
  readonly workflowName: string;
  readonly mediaType: GenerationMediaType;
  readonly prompt: string;
  readonly negativePrompt: string;
  readonly width: number;
  readonly height: number;
  readonly count: number;
  readonly visibility: GenerationVisibility;
  readonly promptVisibility: "public" | "hidden";
  readonly creditsReserved: string;
  readonly creditsCharged: string;
  readonly cancelRequested: boolean;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly finishedAt?: string;
  readonly error?: { readonly code: string; readonly message: string };
  readonly images: readonly { readonly id: string; readonly slug: string }[];
  readonly outputs: readonly { readonly id: string; readonly mediaType: GenerationMediaType; readonly url: string; readonly mimeType: string; readonly width: number; readonly height: number; readonly durationSeconds?: number }[];
}

export interface GenerationPage {
  readonly items: readonly GenerationView[];
  readonly nextCursor?: string;
}
