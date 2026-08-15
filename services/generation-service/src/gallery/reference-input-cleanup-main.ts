import { ConsoleStructuredLogger } from "../pipeline/structured-logger.ts";
import { createDatabasePool } from "../database/pool.ts";
import { TencentCosStorage } from "../storage/tencent-cos.storage.ts";
import { loadGalleryConfig } from "./config.ts";

/**
 * Reference-input TTL sweeper.
 *
 * Reference images uploaded for generation live under
 * `temp/inputs/{userId}/{requestId}/`. They are deleted on failed creation and
 * by ComfyUI's finally-cleanup, but a task that is never claimed (or a future
 * non-ComfyUI image provider) would otherwise keep user privacy images in COS
 * forever. This worker lists that prefix and removes objects older than
 * REFERENCE_INPUT_TTL_MINUTES.
 */
const config = loadGalleryConfig();
const logger = new ConsoleStructuredLogger();
const pool = createDatabasePool(config.databaseUrl, { max: 3 });
const cos = new TencentCosStorage(config.cos);
const ttlMs = ttlMinutes() * 60_000;
const pollMs = pollIntervalMinutes() * 60_000;
const controller = new AbortController();
process.once("SIGINT", () => controller.abort());
process.once("SIGTERM", () => controller.abort());

logger.info("gallery.reference_input_cleanup_started", { pollMs, ttlMinutes: ttlMs / 60_000 });
while (!controller.signal.aborted) {
  try { await runOnce(); }
  catch { logger.error("gallery.reference_input_cleanup_cycle_failed", { failureReason: "internal_error" }); }
  await wait(pollMs, controller.signal);
}
await pool.end();

async function runOnce(): Promise<void> {
  if (!cos.listWithTimestamps) { logger.error("gallery.reference_input_cleanup_unavailable", { failureReason: "storage_list_unsupported" }); return; }
  const items = await cos.listWithTimestamps("temp/inputs/");
  const now = Date.now();
  let removed = 0;
  for (const item of items) {
    if (now - item.lastModifiedMs > ttlMs) {
      await cos.delete(item.objectKey);
      removed += 1;
    }
  }
  if (removed) logger.info("gallery.reference_input_cleanup_removed", { count: removed });
}

function ttlMinutes(): number {
  const raw = process.env.REFERENCE_INPUT_TTL_MINUTES?.trim();
  const value = raw ? Number(raw) : 24 * 60;
  if (!Number.isInteger(value) || value <= 0) throw new Error("REFERENCE_INPUT_TTL_MINUTES must be a positive integer");
  return value;
}

function pollIntervalMinutes(): number {
  const raw = process.env.REFERENCE_INPUT_CLEANUP_POLL_MINUTES?.trim();
  const value = raw ? Number(raw) : 60;
  if (!Number.isInteger(value) || value <= 0) throw new Error("REFERENCE_INPUT_CLEANUP_POLL_MINUTES must be a positive integer");
  return value;
}

function wait(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timeout = setTimeout(resolve, milliseconds);
    signal.addEventListener("abort", () => { clearTimeout(timeout); resolve(); }, { once: true });
  });
}
