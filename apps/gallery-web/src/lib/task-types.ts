import type { GenerationStatus } from "./generation-types";

export type TaskModule = "generation";

export interface TaskSummary {
  readonly key: string;
  readonly module: TaskModule;
  readonly sourceId: string;
  readonly title: string;
  readonly mediaType: "image" | "video";
  readonly status: GenerationStatus;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly finishedAt?: string;
  readonly cancelRequested: boolean;
  readonly creditsReserved: string;
  readonly creditsCharged: string;
  readonly error?: { readonly code: string; readonly message: string };
  readonly outputLinks: readonly (
    | { readonly id: string; readonly mediaType: "image"; readonly slug: string }
    | { readonly id: string; readonly mediaType: "video"; readonly url: string; readonly mimeType: string }
  )[];
}

export interface TaskPage {
  readonly items: readonly TaskSummary[];
  readonly nextCursor?: string;
}
