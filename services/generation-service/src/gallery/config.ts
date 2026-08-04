export interface GalleryConfig {
  readonly databaseUrl: string;
  readonly redisUrl?: string;
  readonly host: string;
  readonly port: number;
  readonly trustProxy: boolean;
  readonly cursorSecret: string;
  readonly internalAuthSecret: string;
  readonly cacheTtlSeconds: number;
  readonly deletionRetentionSeconds: number;
  readonly privateUrlTtlSeconds: number;
  readonly deletionPollMs: number;
  readonly deletionBatchSize: number;
  readonly deletionRetryBaseSeconds: number;
  readonly assetHosts: readonly string[];
  readonly cos: {
    readonly secretId: string;
    readonly secretKey: string;
    readonly securityToken?: string;
    readonly bucket: string;
    readonly region: string;
    readonly cdnBaseUrl?: string;
  };
}

export function loadGalleryConfig(env: NodeJS.ProcessEnv = process.env): GalleryConfig {
  const redisUrl = optional(env, "REDIS_URL");
  const securityToken = optional(env, "COS_SECURITY_TOKEN");
  const cdnBaseUrl = optional(env, "COS_CDN_BASE_URL");
  return {
    databaseUrl: required(env, "DATABASE_URL"),
    ...(redisUrl ? { redisUrl } : {}),
    host: optional(env, "GALLERY_HOST") ?? "127.0.0.1",
    port: integer(env, "GALLERY_PORT", 3101, 1, 65535),
    trustProxy: booleanValue(env, "GALLERY_TRUST_PROXY", false),
    cursorSecret: secret(env, "GALLERY_CURSOR_SECRET"),
    internalAuthSecret: secret(env, "GALLERY_INTERNAL_HMAC_SECRET"),
    cacheTtlSeconds: integer(env, "GALLERY_CACHE_TTL_SECONDS", 30, 1, 3600),
    deletionRetentionSeconds: integer(env, "GALLERY_DELETION_RETENTION_SECONDS", 86400, 0, 2_592_000),
    privateUrlTtlSeconds: integer(env, "GALLERY_PRIVATE_URL_TTL_SECONDS", 300, 30, 3600),
    deletionPollMs: integer(env, "GALLERY_DELETION_POLL_MS", 30_000, 1_000, 300_000),
    deletionBatchSize: integer(env, "GALLERY_DELETION_BATCH_SIZE", 20, 1, 100),
    deletionRetryBaseSeconds: integer(env, "GALLERY_DELETION_RETRY_BASE_SECONDS", 60, 1, 3600),
    assetHosts: hostList(env, "GALLERY_ASSET_HOSTS"),
    cos: {
      secretId: required(env, "COS_SECRET_ID"),
      secretKey: required(env, "COS_SECRET_KEY"),
      ...(securityToken ? { securityToken } : {}),
      bucket: required(env, "COS_BUCKET"),
      region: required(env, "COS_REGION"),
      ...(cdnBaseUrl ? { cdnBaseUrl } : {}),
    },
  };
}

function required(env: NodeJS.ProcessEnv, key: string): string {
  const value = optional(env, key);
  if (!value) throw new Error(`Missing required Gallery configuration: ${key}`);
  return value;
}
function optional(env: NodeJS.ProcessEnv, key: string): string | undefined { return env[key]?.trim() || undefined; }
function secret(env: NodeJS.ProcessEnv, key: string): string {
  const value = required(env, key);
  if (Buffer.byteLength(value, "utf8") < 32) throw new Error(`${key} must contain at least 32 bytes`);
  return value;
}
function integer(env: NodeJS.ProcessEnv, key: string, fallback: number, min: number, max: number): number {
  const raw = optional(env, key);
  const value = raw === undefined ? fallback : Number(raw);
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`${key} must be an integer between ${min} and ${max}`);
  return value;
}
function booleanValue(env: NodeJS.ProcessEnv, key: string, fallback: boolean): boolean {
  const raw = optional(env, key)?.toLowerCase();
  if (raw === undefined) return fallback;
  if (raw === "true") return true;
  if (raw === "false") return false;
  throw new Error(`${key} must be true or false`);
}
function hostList(env: NodeJS.ProcessEnv, key: string): readonly string[] {
  const values = required(env, key).split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);
  if (values.length === 0 || values.some((value) => !/^[a-z0-9.-]+$/.test(value))) throw new Error(`${key} must be a comma-separated hostname allowlist`);
  return [...new Set(values)];
}
