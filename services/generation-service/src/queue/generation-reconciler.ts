import type { Pool, PoolClient, QueryResultRow } from "pg";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";

export interface GenerationReconcilerOptions {
  readonly runningTimeoutMs: number;
  readonly batchSize: number;
}

interface StaleJobRow extends QueryResultRow {
  id: string;
  credits_reserved: string;
  credit_tier: "free" | "member";
  cancel_requested_at: Date | null;
}

/** Repairs terminal state after an interrupted worker or an expired queue lock. */
export class GenerationReconciler {
  readonly #pool: Pool;
  readonly #logger: StructuredLogger;
  readonly #timeoutMs: number;
  readonly #batchSize: number;

  constructor(pool: Pool, logger: StructuredLogger, options: GenerationReconcilerOptions) {
    if (!Number.isSafeInteger(options.runningTimeoutMs) || options.runningTimeoutMs < 60_000) throw new TypeError("runningTimeoutMs must be at least one minute");
    if (!Number.isSafeInteger(options.batchSize) || options.batchSize < 1 || options.batchSize > 1_000) throw new TypeError("batchSize must be between 1 and 1000");
    this.#pool = pool;
    this.#logger = logger;
    this.#timeoutMs = options.runningTimeoutMs;
    this.#batchSize = options.batchSize;
  }

  async runOnce(): Promise<number> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const rows = await client.query<StaleJobRow>(`SELECT id, credits_reserved, credit_tier, cancel_requested_at
        FROM ai.generation_jobs j
        WHERE j.status = 'running'
          AND j.updated_at < now() - (
            GREATEST(
              $1::bigint,
              COALESCE((
                SELECT max(wb.timeout_seconds) * 1000
                FROM ai.workflow_provider_bindings wb
                WHERE wb.workflow_version_id = j.workflow_version_id AND wb.is_enabled
              ), 0)
            ) * interval '1 millisecond'
          )
        ORDER BY j.updated_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT $2`, [this.#timeoutMs, this.#batchSize]);
      for (const job of rows.rows) await this.reconcileLocked(client, job);
      await client.query("COMMIT");
      if (rows.rowCount) this.#logger.error("queue.generation_reconciled", { count: rows.rowCount });
      return rows.rowCount ?? 0;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  private async reconcileLocked(client: PoolClient, job: StaleJobRow): Promise<void> {
    const cancelled = Boolean(job.cancel_requested_at);
    const status = cancelled ? "cancelled" : "failed";
    const code = cancelled ? "cancellation_reconciled" : "worker_timeout";
    await client.query(`UPDATE ai.generation_attempts
      SET status = $2, error_code = $3, error_message = $4, retryable = false, finished_at = now()
      WHERE job_id = $1 AND status = 'running'`, [job.id, status, code, cancelled ? "Cancellation reconciled after worker timeout" : "Generation worker timed out"]);
    await client.query(`UPDATE ai.generation_jobs
      SET status = $2, error_code = $3, error_message = $4, finished_at = now()
      WHERE id = $1 AND status = 'running'`, [job.id, status, code, cancelled ? "Cancellation reconciled after worker timeout" : "Generation worker timed out"]);
    if (Number(job.credits_reserved) > 0) await releaseCredits(client, job.id, job.credit_tier);
    await client.query(`INSERT INTO ai.audit_logs (actor_type, action, resource_type, resource_id, metadata)
      VALUES ('worker', 'generation.reconciled', 'generation_job', $1, jsonb_build_object('status', $2, 'reason', $3))`, [job.id, status, code]);
  }
}

async function releaseCredits(client: PoolClient, jobId: string, tier: "free" | "member"): Promise<void> {
  const active = await client.query("SELECT 1 FROM ai.credit_reservations WHERE generation_job_id = $1 AND status = 'active'", [jobId]);
  if (!active.rowCount) return;
  const fn = tier === "member" ? "ai.release_member_generation_credits" : "ai.release_generation_credits";
  await client.query(`SELECT * FROM ${fn}($1, $2)`, [jobId, `generation-release:${jobId}`]);
}
