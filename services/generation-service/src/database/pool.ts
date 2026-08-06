import { Pool, type PoolConfig } from "pg";

const DEFAULT_CONNECTION_TIMEOUT_MS = 15_000;
const DEFAULT_IDLE_TIMEOUT_MS = 30_000;
const KEEP_ALIVE_INITIAL_DELAY_MS = 30_000;

export interface DatabasePoolOptions {
  /** Maximum number of clients in the pool. */
  readonly max?: number;
}

/**
 * Create a PostgreSQL connection pool tuned for long-lived public-internet
 * connections (e.g. Tencent Cloud -> Prisma Postgres / Neon).
 *
 * - connectionTimeoutMillis is configurable via DATABASE_CONNECTION_TIMEOUT_MS
 *   (default 15s) because a 5s budget is too tight for cross-border TLS setup.
 * - TCP keepalive is enabled so silently dropped connections fail fast.
 */
export function createDatabasePool(url: string, options: DatabasePoolOptions = {}): Pool {
  const connectionTimeoutMillis = positiveInteger(
    process.env.DATABASE_CONNECTION_TIMEOUT_MS,
    DEFAULT_CONNECTION_TIMEOUT_MS,
    "DATABASE_CONNECTION_TIMEOUT_MS",
  );
  const idleTimeoutMillis = positiveInteger(
    process.env.DATABASE_IDLE_TIMEOUT_MS,
    DEFAULT_IDLE_TIMEOUT_MS,
    "DATABASE_IDLE_TIMEOUT_MS",
  );
  const poolConfig: PoolConfig = {
    connectionString: url,
    max: options.max ?? 10,
    idleTimeoutMillis,
    connectionTimeoutMillis,
    keepAlive: true,
    keepAliveInitialDelayMillis: KEEP_ALIVE_INITIAL_DELAY_MS,
    application_name: "mindfulpenpal-ai",
  };
  return new Pool(poolConfig);
}

function positiveInteger(raw: string | undefined, fallback: number, name: string): number {
  const value = raw?.trim() ? Number(raw) : fallback;
  if (!Number.isSafeInteger(value) || value < 500 || value > 120_000) {
    throw new Error(`${name} must be an integer between 500 and 120000`);
  }
  return value;
}
