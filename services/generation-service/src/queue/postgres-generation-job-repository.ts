import { randomUUID } from "node:crypto";
import type { Pool, PoolClient, QueryResultRow } from "pg";
import type { DefaultModerationStatus } from "../generation/types.ts";
import type { ProductionGenerationResult } from "../pipeline/production-generation-pipeline.ts";
import { PostgresProviderCatalog } from "../providers/postgres-catalog.ts";
import type { ProviderAttemptEvent } from "../providers/multi-provider-executor.ts";
import type { GenerationRequest, JsonObject } from "../providers/types.ts";
import type { GenerationJobClaim, GenerationJobRepository, QueueAttemptDescriptor, SafeQueueFailure } from "./types.ts";

interface ClaimRow extends QueryResultRow {
  id: string; status: "pending" | "running" | "completed" | "failed" | "cancelled"; cancel_requested_at: Date | null; credits_reserved: string;
  workflow_version_id: string; workflow_id: string; workflow_version: number; workflow_kind: string; user_id: number | null; owner_email: string | null;
  prompt: string; negative_prompt: string; input_params: JsonObject; requested_width: number; requested_height: number; requested_count: number;
  request_id: string | null;
}

export class PostgresGenerationJobRepository implements GenerationJobRepository {
  readonly #pool: Pool;
  readonly #catalog: PostgresProviderCatalog;
  readonly #defaultModerationStatus: DefaultModerationStatus;
  constructor(pool: Pool, options: { readonly defaultModerationStatus?: DefaultModerationStatus } = {}) {
    this.#pool = pool;
    this.#catalog = new PostgresProviderCatalog(pool);
    this.#defaultModerationStatus = options.defaultModerationStatus ?? "pending";
  }

  async claim(jobId: string, _descriptor: QueueAttemptDescriptor): Promise<GenerationJobClaim> {
    const client = await this.#pool.connect();
    let row: ClaimRow | undefined;
    try {
      await client.query("BEGIN");
      const result = await client.query<ClaimRow>(`SELECT j.id, j.status, j.cancel_requested_at, j.credits_reserved, j.workflow_version_id,
          w.id AS workflow_id, v.version AS workflow_version, w.category AS workflow_kind,
          j.user_id, u.email AS owner_email,
          j.prompt, j.negative_prompt, j.input_params, j.requested_width, j.requested_height, j.requested_count,
          (SELECT payload->>'requestId' FROM ai.outbox_events WHERE aggregate_id = j.id AND event_type = 'generation.requested' ORDER BY created_at LIMIT 1) AS request_id
        FROM ai.generation_jobs j
        JOIN ai.workflow_versions v ON v.id = j.workflow_version_id
        JOIN ai.workflows w ON w.id = v.workflow_id
        LEFT JOIN public.users u ON u.id = j.user_id
        WHERE j.id = $1 FOR UPDATE OF j`, [jobId]);
      row = result.rows[0];
      if (!row) throw new Error("generation_job_not_found");
      if (row.status === "completed") {
        const assets = await client.query<{ url: string }>(`SELECT COALESCE(a.public_url, '') AS url FROM ai.images i
          JOIN ai.image_assets a ON a.image_id = i.id AND a.variant = 'original' WHERE i.job_id = $1 ORDER BY i.created_at`, [jobId]);
        const provider = await client.query<{ code: string }>("SELECT p.code FROM ai.generation_jobs j JOIN ai.providers p ON p.id = j.selected_provider_id WHERE j.id = $1", [jobId]);
        await client.query("COMMIT");
        return { kind: "completed", assetUrls: assets.rows.map((item) => item.url).filter(Boolean), ...(provider.rows[0]?.code ? { providerCode: provider.rows[0].code } : {}) };
      }
      if (row.status === "cancelled" || row.cancel_requested_at) {
        // A cancelled request may be reclaimed after a worker restart or stall.
        // Finalize the database state here so the task cannot stay "running"
        // forever and reserved credits are always released.
        if (row.status !== "cancelled") {
          await client.query("UPDATE ai.generation_jobs SET status = 'cancelled', cancel_requested_at = COALESCE(cancel_requested_at, now()), finished_at = now() WHERE id = $1", [jobId]);
          if (Number(row.credits_reserved) > 0) await releaseCredits(client, jobId, row.credit_tier);
        }
        await client.query("COMMIT");
        return { kind: "cancelled" };
      }
      await client.query("UPDATE ai.generation_jobs SET status = 'running', started_at = COALESCE(started_at, now()), error_code = NULL, error_message = NULL WHERE id = $1", [jobId]);
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined); throw error;
    } finally { client.release(); }

    const bindings = await this.#catalog.bindingsFor(row.workflow_version_id);
    const owner = ownerKey(row.owner_email, row.user_id);
    const request: GenerationRequest = {
      jobId: row.id,
      workflow: { workflowId: row.workflow_id, workflowVersionId: row.workflow_version_id, version: row.workflow_version, kind: row.workflow_kind },
      mode: "text-to-image", prompt: row.prompt, negativePrompt: row.negative_prompt,
      width: row.requested_width, height: row.requested_height, count: row.requested_count,
      ...(owner === undefined ? {} : { ownerKey: owner }),
      ...(typeof row.input_params.seed === "number" ? { seed: row.input_params.seed } : {}),
      parameters: row.input_params,
    };
    return { kind: "execute", plan: { request, bindings, context: { requestId: row.request_id ?? randomUUID(), attemptId: randomUUID() } } };
  }

  async markProviderAttempt(jobId: string, _baseAttemptId: string, event: ProviderAttemptEvent): Promise<string> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT id FROM ai.generation_jobs WHERE id = $1 FOR UPDATE", [jobId]);
      const target = await client.query<{ provider_id: string; binding_id: string; provider_model: string | null; estimated_cost: string }>(`SELECT p.id AS provider_id, b.id AS binding_id,
          COALESCE(m.model_code, b.provider_model) AS provider_model, COALESCE(b.estimated_cost, 0) AS estimated_cost
        FROM ai.workflow_provider_bindings b JOIN ai.providers p ON p.id = b.provider_id
        LEFT JOIN ai.provider_models m ON m.id = b.provider_model_id
        WHERE b.id = $1 AND p.code = $2`, [event.bindingId, event.providerCode]);
      const selected = target.rows[0];
      if (!selected) throw new Error("generation_binding_not_found");
      const attemptNo = await client.query<{ value: number }>("SELECT COALESCE(max(attempt_no), 0) + 1 AS value FROM ai.generation_attempts WHERE job_id = $1", [jobId]);
      const attemptId = randomUUID();
      await client.query(`UPDATE ai.generation_attempts SET status = 'failed', error_class = 'upstream',
        error_code = 'provider_attempt_retried', error_message = 'Provider attempt was replaced by a retry or fallback',
        retryable = true, finished_at = now() WHERE job_id = $1 AND status = 'running'`, [jobId]);
      await client.query(`INSERT INTO ai.generation_attempts (
          id, job_id, provider_id, binding_id, attempt_no, status, provider_model, request_snapshot, estimated_cost, started_at
        ) VALUES ($1, $2, $3, $4, $5, 'running', $6, jsonb_build_object('provider_attempt', $7::integer, 'total_call', $8::integer), $9, now())`,
      [attemptId, jobId, selected.provider_id, selected.binding_id, attemptNo.rows[0]?.value ?? 1, selected.provider_model, event.providerAttempt, event.totalCall, selected.estimated_cost]);
      await client.query("UPDATE ai.generation_jobs SET selected_provider_id = $2 WHERE id = $1", [jobId, selected.provider_id]);
      await client.query("COMMIT");
      return attemptId;
    } catch (error) { await client.query("ROLLBACK").catch(() => undefined); throw error; }
    finally { client.release(); }
  }

  async markCompleted(jobId: string, attemptId: string, result: ProductionGenerationResult): Promise<void> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const jobResult = await client.query<{ user_id: number; workflow_version_id: string; prompt: string; negative_prompt: string; visibility: "public" | "private"; prompt_visibility: "public" | "hidden"; credits_reserved: string; credit_tier: "free" | "member"; workflow_name: string }>(`SELECT j.user_id, j.workflow_version_id, j.prompt, j.negative_prompt, j.visibility, j.prompt_visibility, j.credits_reserved, j.credit_tier, w.name AS workflow_name
        FROM ai.generation_jobs j JOIN ai.workflow_versions v ON v.id = j.workflow_version_id JOIN ai.workflows w ON w.id = v.workflow_id WHERE j.id = $1 FOR UPDATE OF j`, [jobId]);
      const job = jobResult.rows[0];
      if (!job) throw new Error("generation_job_not_found");
      const currentStatus = (await client.query<{ status: string }>("SELECT status FROM ai.generation_jobs WHERE id = $1", [jobId])).rows[0]?.status;
      // A cancelled job must never be flipped back to completed (this can race
      // with a cancellation signal when the provider call already finished),
      // otherwise the user would keep the image and get a credit refund too.
      if (currentStatus === "completed" || currentStatus === "cancelled") { await client.query("COMMIT"); return; }
      const provider = await client.query<{ id: string }>("SELECT id FROM ai.providers WHERE code = $1", [result.providerCode]);
      const providerId = provider.rows[0]?.id;
      if (!providerId) throw new Error("generation_provider_not_found");
      await client.query(`UPDATE ai.generation_attempts SET provider_id = $2, status = 'succeeded', external_request_id = $3,
        response_snapshot = $4::jsonb, actual_cost = $6, finished_at = now() WHERE id = $1 AND job_id = $5`, [attemptId, providerId, result.externalRequestId, JSON.stringify(safeProviderMetadata(result.providerMetadata)), jobId, result.actualCost ?? 0]);
      for (const [index, asset] of result.assets.entries()) {
        const image = await client.query<{ id: string }>(`INSERT INTO ai.images (
            job_id, successful_attempt_id, creator_user_id, provider_id, workflow_version_id, slug, title,
            prompt, negative_prompt, provider_code_snapshot, model_snapshot, workflow_name_snapshot,
            width, height, generation_ms, visibility, prompt_visibility, moderation_status, published_at
          ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $7, $12, $13, $14, $15, $16, $17,
            CASE WHEN $17::ai.moderation_status = 'approved' AND $15::ai.image_visibility = 'public' THEN now() ELSE NULL END)
          ON CONFLICT (slug) DO UPDATE SET slug = EXCLUDED.slug RETURNING id`, [jobId, attemptId, job.user_id, providerId, job.workflow_version_id,
          `${jobId}-${index + 1}`, job.workflow_name, job.prompt, job.negative_prompt, result.providerCode, modelFrom(result.providerMetadata), asset.width, asset.height, result.generationDurationMs, job.visibility, job.prompt_visibility, this.#defaultModerationStatus]);
        await client.query(`INSERT INTO ai.image_assets (image_id, variant, storage_provider, bucket, region, object_key, public_url, mime_type, byte_size, width, height, sha256)
          VALUES ($1, 'original', $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
          ON CONFLICT (image_id, variant) DO NOTHING`, [image.rows[0]!.id, asset.storageProvider, asset.bucket, asset.region, asset.objectKey,
          job.visibility === "public" ? asset.url : null, asset.mimeType, asset.byteSize, asset.width, asset.height, asset.sha256]);
      }
      await client.query("UPDATE ai.generation_jobs SET status = 'completed', selected_provider_id = $2, actual_cost = $3, finished_at = now(), error_code = NULL, error_message = NULL WHERE id = $1", [jobId, providerId, result.actualCost ?? 0]);
      if (Number(job.credits_reserved) > 0) {
        const fn = job.credit_tier === "member" ? "ai.settle_member_generation_credits" : "ai.settle_generation_credits";
        await client.query(`SELECT * FROM ${fn}($1, $2, $3)`, [jobId, job.credits_reserved, `generation-settle:${jobId}`]);
      }
      await client.query("COMMIT");
    } catch (error) { await client.query("ROLLBACK").catch(() => undefined); throw error; }
    finally { client.release(); }
  }

  async markFailed(jobId: string, attemptId: string, failure: SafeQueueFailure, willRetry: boolean): Promise<void> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const job = await client.query<{ credits_reserved: string; credit_tier: "free" | "member" }>(`UPDATE ai.generation_jobs SET status = $2, error_code = $3, error_message = $4,
        finished_at = CASE WHEN $2 = 'failed' THEN now() ELSE NULL END
        WHERE id = $1 AND status = 'running' RETURNING credits_reserved, credit_tier`, [jobId, willRetry ? "pending" : "failed", failure.code, safeMessage(failure.message)]);
      if (job.rowCount) {
        await client.query(`UPDATE ai.generation_attempts SET status = 'failed', error_class = $2, error_code = $3, error_message = $4, retryable = $5, finished_at = now()
          WHERE id = $1 AND job_id = $6 AND status = 'running'`, [attemptId, failure.category, failure.code, safeMessage(failure.message), failure.retryable, jobId]);
      }
      if (!willRetry && Number(job.rows[0]?.credits_reserved ?? 0) > 0) await releaseCredits(client, jobId, job.rows[0]!.credit_tier);
      await client.query("COMMIT");
    } catch (error) { await client.query("ROLLBACK").catch(() => undefined); throw error; }
    finally { client.release(); }
  }

  async markCancelled(jobId: string, attemptId: string, reason: string): Promise<void> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const job = await client.query<{ credits_reserved: string; credit_tier: "free" | "member" }>("UPDATE ai.generation_jobs SET status = 'cancelled', cancel_requested_at = COALESCE(cancel_requested_at, now()), finished_at = now() WHERE id = $1 AND status IN ('pending', 'running') RETURNING credits_reserved, credit_tier", [jobId]);
      if (job.rowCount) {
        await client.query("UPDATE ai.generation_attempts SET status = 'cancelled', error_code = $2, finished_at = now() WHERE id = $1 AND job_id = $3 AND status = 'running'", [attemptId, reason.slice(0, 128), jobId]);
      }
      if (Number(job.rows[0]?.credits_reserved ?? 0) > 0) await releaseCredits(client, jobId, job.rows[0]!.credit_tier);
      await client.query("COMMIT");
    } catch (error) { await client.query("ROLLBACK").catch(() => undefined); throw error; }
    finally { client.release(); }
  }
}

async function releaseCredits(client: PoolClient, jobId: string, creditTier: "free" | "member"): Promise<void> {
  const active = await client.query("SELECT 1 FROM ai.credit_reservations WHERE generation_job_id = $1 AND status = 'active'", [jobId]);
  if (active.rowCount) {
    const fn = creditTier === "member" ? "ai.release_member_generation_credits" : "ai.release_generation_credits";
    await client.query(`SELECT * FROM ${fn}($1, $2)`, [jobId, `generation-release:${jobId}`]);
  }
}
function safeMessage(value: string): string { return value.replace(/[\r\n]/g, " ").slice(0, 500); }
function safeProviderMetadata(value: Readonly<Record<string, unknown>>): Record<string, unknown> {
  const allowed = new Set(["model", "outputCount", "workflowName", "workflowVersion", "workflowDigest"]);
  return Object.fromEntries(Object.entries(value).filter(([key, item]) => allowed.has(key) && (typeof item === "string" || typeof item === "number" || typeof item === "boolean" || item === null)));
}
function modelFrom(value: Readonly<Record<string, unknown>>): string | null { return typeof value.model === "string" ? value.model.slice(0, 128) : null; }
function ownerKey(email: string | null, userId: number | null): string | undefined {
  if (userId === null) return undefined;
  const local = (email ?? "").split("@")[0]?.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
  return `${local || "user"}-${userId}`.slice(0, 80);
}
