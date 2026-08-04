import { Pool } from "pg";
import { ConsoleStructuredLogger } from "../pipeline/structured-logger.ts";
import { TencentCosStorage } from "../storage/tencent-cos.storage.ts";
import { GalleryAssetDeletionWorker } from "./asset-deletion-worker.ts";
import { TencentCosGalleryAssetUrlResolver } from "./asset-url.ts";
import { loadGalleryConfig } from "./config.ts";
import { PostgresGalleryRepository } from "./postgres-gallery-repository.ts";

const config = loadGalleryConfig();
const logger = new ConsoleStructuredLogger();
const pool = new Pool({ connectionString: config.databaseUrl, max: 3, idleTimeoutMillis: 30_000, connectionTimeoutMillis: 5_000 });
const assets = new TencentCosGalleryAssetUrlResolver({ ...config.cos, allowedPublicHosts: config.assetHosts, privateUrlTtlSeconds: config.privateUrlTtlSeconds });
const repository = new PostgresGalleryRepository(pool, assets);
const cos = new TencentCosStorage(config.cos);
const worker = new GalleryAssetDeletionWorker({ repository, storageProviders: [cos], logger, batchSize: config.deletionBatchSize, baseRetrySeconds: config.deletionRetryBaseSeconds });
const controller = new AbortController();
process.once("SIGINT", () => controller.abort());
process.once("SIGTERM", () => controller.abort());

logger.info("gallery.deletion_worker_started", { pollMs: config.deletionPollMs, batchSize: config.deletionBatchSize });
while (!controller.signal.aborted) {
  try { await worker.runOnce(); }
  catch { logger.error("gallery.deletion_worker_cycle_failed", { failureReason: "internal_error" }); }
  await wait(config.deletionPollMs, controller.signal);
}
await pool.end();

function wait(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timeout = setTimeout(resolve, milliseconds);
    signal.addEventListener("abort", () => { clearTimeout(timeout); resolve(); }, { once: true });
  });
}
