import type { ViewerContext } from "../gallery/types.ts";
import { GenerationError } from "../generation/errors.ts";
import { GenerationTaskSource } from "./generation-task-source.ts";
import type { TaskListRequest, TaskModule, TaskPage } from "./types.ts";

type TaskSource = { readonly module: TaskModule; list(query: Omit<TaskListRequest, "module">, viewer: ViewerContext): Promise<TaskPage> };

/**
 * Additive platform task read model. Sources remain the owners of their data
 * and authorization; this layer intentionally does not introduce a second
 * mutable task record beside PostgreSQL business records.
 */
export class TaskCenterService {
  readonly #sources: ReadonlyMap<TaskModule, TaskSource>;

  constructor(sources: readonly TaskSource[]) {
    if (sources.length === 0) throw new Error("TaskCenterService requires at least one task source");
    this.#sources = new Map(sources.map((source) => [source.module, source]));
    if (this.#sources.size !== sources.length) throw new Error("TaskCenterService task modules must be unique");
  }

  async list(query: TaskListRequest, viewer: ViewerContext): Promise<TaskPage> {
    const source = this.sourceFor(query.module);
    return source.list({
      ...(query.cursor ? { cursor: query.cursor } : {}),
      ...(query.limit !== undefined ? { limit: query.limit } : {}),
      ...(query.status ? { status: query.status } : {}),
    }, viewer);
  }

  private sourceFor(module: TaskModule | undefined): TaskSource {
    if (module) {
      const source = this.#sources.get(module);
      if (source) return source;
      throw new GenerationError("invalid_request", "task module is invalid", 400);
    }
    if (this.#sources.size === 1) return this.#sources.values().next().value as TaskSource;
    throw new GenerationError("invalid_request", "task module is required", 400);
  }
}

export function generationTaskCenter(generation: import("../generation/generation-service.ts").GenerationService): TaskCenterService {
  return new TaskCenterService([new GenerationTaskSource(generation)]);
}
