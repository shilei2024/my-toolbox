import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import type { StorageProvider } from "../storage/storage-provider.ts";
import type { GalleryRepository } from "./repository.ts";

export class GalleryAssetDeletionWorker {
  readonly #repository: GalleryRepository;
  readonly #storageProviders: ReadonlyMap<string, StorageProvider>;
  readonly #logger: StructuredLogger;
  readonly #batchSize: number;
  readonly #baseRetrySeconds: number;

  constructor(options: { repository: GalleryRepository; storageProviders: readonly StorageProvider[]; logger: StructuredLogger; batchSize?: number; baseRetrySeconds?: number }) {
    this.#repository = options.repository;
    this.#storageProviders = new Map(options.storageProviders.map((provider) => [provider.code, provider]));
    this.#logger = options.logger;
    this.#batchSize = options.batchSize ?? 20;
    this.#baseRetrySeconds = options.baseRetrySeconds ?? 60;
  }

  async runOnce(): Promise<{ readonly claimed: number; readonly completed: number; readonly failed: number }> {
    const tasks = await this.#repository.claimDeletionTasks(this.#batchSize);
    let completed = 0;
    let failed = 0;
    for (const task of tasks) {
      try {
        for (const asset of task.assets) {
          const storage = this.#storageProviders.get(asset.storageProvider);
          if (!storage) throw new Error("Storage provider is unavailable");
          await storage.delete(asset.objectKey);
        }
        await this.#repository.completeDeletion(task.imageId);
        completed += 1;
        this.#logger.info("gallery.assets_deleted", { imageId: task.imageId, objectCount: task.assets.length });
      } catch {
        failed += 1;
        const retrySeconds = Math.min(3600, this.#baseRetrySeconds * 2 ** Math.max(0, task.attempt - 1));
        const retryAt = new Date(Date.now() + retrySeconds * 1000);
        await this.#repository.failDeletion(task.imageId, "storage_delete_failed", retryAt);
        this.#logger.error("gallery.asset_deletion_failed", { imageId: task.imageId, failureReason: "storage_delete_failed" });
      }
    }
    return { claimed: tasks.length, completed, failed };
  }
}
