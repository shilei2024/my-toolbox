import path from "node:path";
import { Pool } from "pg";
import { ComfyUIClient } from "../comfyui/client.ts";
import { ComfyUIProvider } from "../comfyui/provider.ts";
import { loadPhase4Config } from "../config.ts";
import { ImagePersistenceService } from "../pipeline/image-persistence.ts";
import { PollingService } from "../pipeline/polling-service.ts";
import { ProductionGenerationPipeline } from "../pipeline/production-generation-pipeline.ts";
import { ConsoleStructuredLogger } from "../pipeline/structured-logger.ts";
import { MockImageProvider } from "../providers/mock.provider.ts";
import { PostgresProviderCatalog } from "../providers/postgres-catalog.ts";
import { ProviderRegistry } from "../providers/registry.ts";
import { ProviderSelectionPolicy } from "../providers/selection-policy.ts";
import { loadPhase9RemoteProviderConfig } from "../remote-providers/config.ts";
import { registerPhase9RemoteProviders } from "../remote-providers/register.ts";
import { TencentCosStorage } from "../storage/tencent-cos.storage.ts";
import { WorkflowLoader } from "../workflows/workflow-loader.ts";
import { loadGenerationQueueConfig } from "./config.ts";
import { GenerationQueueProcessor } from "./generation-queue-processor.ts";
import { GenerationWorkerRuntime } from "./generation-worker.ts";
import { PostgresGenerationJobRepository } from "./postgres-generation-job-repository.ts";
import { createGenerationRedisConnections } from "./redis-connections.ts";
import { parseDefaultModeration } from "../generation/types.ts";

const databaseUrl = required("DATABASE_URL");
const queueConfig = loadGenerationQueueConfig();
const logger = new ConsoleStructuredLogger();
const pool = new Pool({ connectionString: databaseUrl, max: 10, idleTimeoutMillis: 30_000, connectionTimeoutMillis: 5_000 });
const registry = new ProviderRegistry();

if (process.env.COMFYUI_BASE_URL?.trim()) {
  const phase4 = loadPhase4Config();
  registry.register(new ComfyUIProvider(new ComfyUIClient(phase4.comfyui), new WorkflowLoader(phase4.comfyui.workflowDirectory), {
    model: required("COMFYUI_DEFAULT_MODEL"),
    steps: integer("COMFYUI_DEFAULT_STEPS", 28, 1, 1000),
    cfg: decimal("COMFYUI_DEFAULT_CFG", 7, 0, 100),
    sampler: process.env.COMFYUI_DEFAULT_SAMPLER?.trim() || "euler",
    scheduler: process.env.COMFYUI_DEFAULT_SCHEDULER?.trim() || "normal",
  }));
}
registerPhase9RemoteProviders(registry, loadPhase9RemoteProviderConfig());
if (boolean("GENERATION_ALLOW_MOCK_PROVIDER", false)) {
  if ((process.env.APP_ENV?.trim().toLowerCase() ?? "development") === "production") throw new Error("Mock provider cannot run in production");
  registry.register(new MockImageProvider({ asynchronous: true, latencyMs: integer("GENERATION_MOCK_LATENCY_MS", 1200, 0, 60_000) }));
}
if (registry.list().length === 0) throw new Error("No generation provider is configured");
await new PostgresProviderCatalog(pool).refreshRegistry(registry);

const storage = new TencentCosStorage({
  secretId: required("COS_SECRET_ID"), secretKey: required("COS_SECRET_KEY"),
  ...(process.env.COS_SECURITY_TOKEN?.trim() ? { securityToken: process.env.COS_SECURITY_TOKEN.trim() } : {}),
  bucket: required("COS_BUCKET"), region: required("COS_REGION"),
  ...(process.env.COS_CDN_BASE_URL?.trim() ? { cdnBaseUrl: process.env.COS_CDN_BASE_URL.trim().replace(/\/+$/, "") } : {}),
});
const temporaryRoot = path.resolve(required("GENERATION_TEMP_DIR"));
const polling = new PollingService({ intervalMs: integer("GENERATION_POLL_INTERVAL_MS", 1000, 100, 60_000), maxAttempts: integer("GENERATION_POLL_MAX_ATTEMPTS", 600, 1, 7200) });
const persistence = new ImagePersistenceService(storage, temporaryRoot, integer("GENERATION_REMOTE_DOWNLOAD_TIMEOUT_MS", 60_000, 1000, 300_000));
const pipeline = new ProductionGenerationPipeline(polling, persistence, logger);
const processor = new GenerationQueueProcessor(new PostgresGenerationJobRepository(pool, { defaultModerationStatus: parseDefaultModeration(process.env.GALLERY_DEFAULT_MODERATION) }), new ProviderSelectionPolicy(registry), pipeline, logger, {
  retryBaseMs: integer("GENERATION_PROVIDER_RETRY_BASE_MS", 500, 0, 30_000), maxTotalCalls: integer("GENERATION_PROVIDER_MAX_TOTAL_CALLS", 6, 1, 10),
});
const redis = createGenerationRedisConnections(queueConfig, logger);
const runtime = new GenerationWorkerRuntime(processor, redis.worker, redis.subscriber, queueConfig, logger);
await runtime.start();
logger.info("queue.generation_worker_started", { providers: registry.list().map((provider) => provider.descriptor.code), concurrency: queueConfig.concurrency });

let stopping = false;
const shutdown = async () => {
  if (stopping) return;
  stopping = true;
  await runtime.close();
  await Promise.allSettled([redis.producer.quit(), redis.publisher.quit()]);
  await pool.end();
  logger.info("queue.generation_worker_stopped", {});
};
process.once("SIGINT", () => { void shutdown(); });
process.once("SIGTERM", () => { void shutdown(); });

function required(name: string): string { const value = process.env[name]?.trim(); if (!value) throw new Error(`${name} is required`); return value; }
function integer(name: string, fallback: number, min: number, max: number): number { const raw = process.env[name]?.trim(); const value = raw ? Number(raw) : fallback; if (!Number.isSafeInteger(value) || value < min || value > max) throw new Error(`${name} must be an integer between ${min} and ${max}`); return value; }
function boolean(name: string, fallback: boolean): boolean { const raw = process.env[name]?.trim().toLowerCase(); if (!raw) return fallback; if (raw === "true") return true; if (raw === "false") return false; throw new Error(`${name} must be true or false`); }
function decimal(name: string, fallback: number, min: number, max: number): number { const raw = process.env[name]?.trim(); const value = raw ? Number(raw) : fallback; if (!Number.isFinite(value) || value < min || value > max) throw new Error(`${name} must be a number between ${min} and ${max}`); return value; }
