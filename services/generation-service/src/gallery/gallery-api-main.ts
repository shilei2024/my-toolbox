import { Redis } from "ioredis";
import { Pool } from "pg";
import { AdminService } from "../admin/admin-service.ts";
import { PostgresAdminRepository } from "../admin/postgres-admin-repository.ts";
import { BillingService } from "../billing/billing-service.ts";
import { loadBillingConfig } from "../billing/config.ts";
import { PaymentProviderRegistry } from "../billing/payment-provider.ts";
import { PostgresBillingRepository } from "../billing/postgres-billing-repository.ts";
import { StripePaymentProvider } from "../billing/stripe-provider.ts";
import { ConsoleStructuredLogger } from "../pipeline/structured-logger.ts";
import { TencentCosGalleryAssetUrlResolver } from "./asset-url.ts";
import { NoopGalleryCache } from "./cache.ts";
import { loadGalleryConfig } from "./config.ts";
import { GalleryCursorCodec } from "./cursor.ts";
import { GalleryService } from "./gallery-service.ts";
import { createGalleryHttpServer } from "./http-server.ts";
import { InternalViewerContextCodec } from "./internal-auth.ts";
import { PostgresGalleryRepository } from "./postgres-gallery-repository.ts";
import { RedisGalleryCache } from "./redis-gallery-cache.ts";

const config = loadGalleryConfig();
const billingConfig = loadBillingConfig();
const logger = new ConsoleStructuredLogger();
const pool = new Pool({ connectionString: config.databaseUrl, max: 10, idleTimeoutMillis: 30_000, connectionTimeoutMillis: 5_000 });
const redis = config.redisUrl ? new Redis(config.redisUrl, { lazyConnect: true, maxRetriesPerRequest: 1, enableOfflineQueue: false }) : undefined;
if (redis) await redis.connect();
const assets = new TencentCosGalleryAssetUrlResolver({ ...config.cos, allowedPublicHosts: config.assetHosts, privateUrlTtlSeconds: config.privateUrlTtlSeconds });
const repository = new PostgresGalleryRepository(pool, assets);
const service = new GalleryService({
  repository,
  cursor: new GalleryCursorCodec(config.cursorSecret),
  cache: redis ? new RedisGalleryCache(redis) : new NoopGalleryCache(),
  logger,
  cacheTtlSeconds: config.cacheTtlSeconds,
  deletionRetentionSeconds: config.deletionRetentionSeconds,
});
const admin = new AdminService({ repository: new PostgresAdminRepository(pool, assets), logger, onContentChanged: () => service.invalidatePublicData() });
const paymentProviders = new PaymentProviderRegistry();
if (billingConfig.stripe) paymentProviders.register(new StripePaymentProvider(billingConfig.stripe.webhookSecret, billingConfig.stripe.secretKey));
const billing = new BillingService({ repository: new PostgresBillingRepository(pool), providers: paymentProviders, logger, publicBaseUrl: billingConfig.publicBaseUrl });
const app = await createGalleryHttpServer({ service, admin, billing, auth: new InternalViewerContextCodec(config.internalAuthSecret), logger, trustProxy: config.trustProxy, ...(redis ? { redis } : {}) });

await app.listen({ host: config.host, port: config.port });
logger.info("gallery.api_started", { host: config.host, port: config.port });

const shutdown = async (): Promise<void> => {
  await app.close();
  await pool.end();
  if (redis) await redis.quit();
};
process.once("SIGINT", () => { void shutdown(); });
process.once("SIGTERM", () => { void shutdown(); });
