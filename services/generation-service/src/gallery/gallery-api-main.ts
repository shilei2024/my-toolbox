import { Redis } from "ioredis";
import { AdminService } from "../admin/admin-service.ts";
import { PostgresAdminRepository } from "../admin/postgres-admin-repository.ts";
import { BillingService } from "../billing/billing-service.ts";
import { loadBillingConfig } from "../billing/config.ts";
import { PaymentProviderRegistry } from "../billing/payment-provider.ts";
import { PostgresBillingRepository } from "../billing/postgres-billing-repository.ts";
import { createDatabasePool } from "../database/pool.ts";
import { StripePaymentProvider } from "../billing/stripe-provider.ts";
import { GenerationService } from "../generation/generation-service.ts";
import { PostgresGenerationRepository } from "../generation/postgres-generation-repository.ts";
import { ConsoleStructuredLogger } from "../pipeline/structured-logger.ts";
import { loadGenerationQueueConfig } from "../queue/config.ts";
import { createGenerationQueue, GenerationQueueService } from "../queue/generation-queue-service.ts";
import { TencentCosGalleryAssetUrlResolver } from "./asset-url.ts";
import { NoopGalleryCache } from "./cache.ts";
import { loadGalleryConfig } from "./config.ts";
import { GalleryCursorCodec } from "./cursor.ts";
import { GalleryService } from "./gallery-service.ts";
import { createGalleryHttpServer } from "./http-server.ts";
import { InternalViewerContextCodec } from "./internal-auth.ts";
import { PostgresGalleryRepository } from "./postgres-gallery-repository.ts";
import { RedisGalleryCache } from "./redis-gallery-cache.ts";
import { generationTaskCenter } from "../tasks/task-center-service.ts";
import { TencentCosStorage } from "../storage/tencent-cos.storage.ts";

const config = loadGalleryConfig();
const billingConfig = loadBillingConfig();
const logger = new ConsoleStructuredLogger();
const pool = createDatabasePool(config.databaseUrl, { max: 10 });
const redis = config.redisUrl ? new Redis(config.redisUrl, { lazyConnect: true, maxRetriesPerRequest: 1, enableOfflineQueue: false }) : undefined;
if (redis) await redis.connect();
const assets = new TencentCosGalleryAssetUrlResolver({ ...config.cos, allowedPublicHosts: config.assetHosts, privateUrlTtlSeconds: config.privateUrlTtlSeconds });
const repository = new PostgresGalleryRepository(pool, assets);
const cursorCodec = new GalleryCursorCodec(config.cursorSecret);
const generationStorage = new TencentCosStorage({ secretId: config.cos.secretId, secretKey: config.cos.secretKey, ...(config.cos.securityToken ? { securityToken: config.cos.securityToken } : {}), bucket: config.cos.bucket, region: config.cos.region, ...(config.cos.cdnBaseUrl ? { cdnBaseUrl: config.cos.cdnBaseUrl } : {}) });
const service = new GalleryService({
  repository,
  cursor: cursorCodec,
  cache: redis ? new RedisGalleryCache(redis) : new NoopGalleryCache(),
  logger,
  cacheTtlSeconds: config.cacheTtlSeconds,
  deletionRetentionSeconds: config.deletionRetentionSeconds,
});
const paymentProviders = new PaymentProviderRegistry();
if (billingConfig.stripe) paymentProviders.register(new StripePaymentProvider(billingConfig.stripe.webhookSecret, billingConfig.stripe.secretKey));
const billing = new BillingService({ repository: new PostgresBillingRepository(pool), providers: paymentProviders, logger, publicBaseUrl: billingConfig.publicBaseUrl, signupGrant: billingConfig.signupGrant });
const configuredGenerationCreditCost = process.env.GENERATION_DEFAULT_CREDIT_COST?.trim();
const generationQueue = config.redisUrl ? (() => {
  const queueConfig = loadGenerationQueueConfig();
  const producer = new Redis(queueConfig.redisUrl, { connectionName: "generation-api-producer", maxRetriesPerRequest: 1, enableOfflineQueue: false });
  const publisher = new Redis(queueConfig.redisUrl, { connectionName: "generation-api-cancel", maxRetriesPerRequest: 1, enableOfflineQueue: false });
  return new GenerationQueueService(createGenerationQueue(producer, queueConfig, logger), publisher, queueConfig);
})() : undefined;
const admin = new AdminService({ repository: new PostgresAdminRepository(pool, assets), logger, onContentChanged: () => service.invalidatePublicData(), ...(generationQueue ? { queueObservability: generationQueue } : {}) });
const generation = new GenerationService({ repository: new PostgresGenerationRepository(pool), cursor: cursorCodec, storage: generationStorage, ...(configuredGenerationCreditCost ? { defaultCreditCost: configuredGenerationCreditCost } : {}), ...(generationQueue ? { cancellation: generationQueue } : {}), ready: Boolean(generationQueue) });
const tasks = generationTaskCenter(generation);
const app = await createGalleryHttpServer({ service, admin, billing, generation, tasks, auth: new InternalViewerContextCodec(config.internalAuthSecret), logger, trustProxy: config.trustProxy, ...(redis ? { redis } : {}) });

await app.listen({ host: config.host, port: config.port });
logger.info("gallery.api_started", { host: config.host, port: config.port });

const shutdown = async (): Promise<void> => {
  await app.close();
  if (generationQueue) await generationQueue.close();
  await pool.end();
  if (redis) await redis.quit();
};
process.once("SIGINT", () => { void shutdown(); });
process.once("SIGTERM", () => { void shutdown(); });
