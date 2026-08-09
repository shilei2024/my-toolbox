import type { ViewerContext } from "../gallery/types.ts";
import type { GenerationService } from "../generation/generation-service.ts";
import type { TaskListRequest, TaskPage, TaskSummary } from "./types.ts";

/** Maps the durable Generation Service task model into the platform task contract. */
export class GenerationTaskSource {
  readonly module = "generation" as const;
  readonly #generation: GenerationService;

  constructor(generation: GenerationService) { this.#generation = generation; }

  async list(query: Omit<TaskListRequest, "module">, viewer: ViewerContext): Promise<TaskPage> {
    const page = await this.#generation.list(query, viewer);
    return {
      items: page.items.map((item): TaskSummary => ({
        key: `${this.module}:${item.id}`,
        module: this.module,
        sourceId: item.id,
        title: item.workflowName,
        mediaType: item.mediaType,
        status: item.status,
        createdAt: item.createdAt,
        updatedAt: item.updatedAt,
        ...(item.finishedAt ? { finishedAt: item.finishedAt } : {}),
        cancelRequested: item.cancelRequested,
        creditsReserved: item.creditsReserved,
        creditsCharged: item.creditsCharged,
        ...(item.error ? { error: item.error } : {}),
        outputLinks: item.mediaType === "video"
          ? item.outputs.filter((output) => output.mediaType === "video").map((output) => ({ id: output.id, mediaType: "video" as const, url: output.url, mimeType: output.mimeType }))
          : item.images.map((image) => ({ ...image, mediaType: "image" as const })),
      })),
      ...(page.nextCursor ? { nextCursor: page.nextCursor } : {}),
    };
  }
}
