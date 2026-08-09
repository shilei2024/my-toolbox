import type { GenerationStatus } from "../generation/types.ts";

export type TaskModule = "generation";

export interface TaskSummary {
  /** Stable across modules: use this key rather than assuming source IDs are globally unique. */
  readonly key: string;
  readonly module: TaskModule;
  readonly sourceId: string;
  readonly title: string;
  readonly status: GenerationStatus;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly finishedAt?: string;
  readonly cancelRequested: boolean;
  readonly creditsReserved: string;
  readonly creditsCharged: string;
  readonly error?: { readonly code: string; readonly message: string };
  readonly outputLinks: readonly { readonly id: string; readonly slug: string }[];
}

export interface TaskListRequest {
  readonly module?: TaskModule;
  readonly cursor?: string;
  readonly limit?: number;
  readonly status?: GenerationStatus;
}

export interface TaskPage {
  readonly items: readonly TaskSummary[];
  readonly nextCursor?: string;
}
