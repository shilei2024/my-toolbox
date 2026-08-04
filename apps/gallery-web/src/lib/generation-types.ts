export type GenerationStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type GenerationVisibility = "public" | "private";

export interface GenerationWorkflow {
  readonly slug: string;
  readonly name: string;
  readonly description: string;
  readonly category: string;
  readonly defaults: { readonly width: number; readonly height: number; readonly count: number; readonly visibility: GenerationVisibility };
  readonly creditCost: string;
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
  readonly promptVisibility: "public" | "hidden";
  readonly creditsReserved: string;
  readonly creditsCharged: string;
  readonly cancelRequested: boolean;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly finishedAt?: string;
  readonly error?: { readonly code: string; readonly message: string };
  readonly images: readonly { readonly id: string; readonly slug: string }[];
}
