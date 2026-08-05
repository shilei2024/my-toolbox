import type { Pool, PoolClient, QueryResultRow } from "pg";
import type { DecodedCursor } from "../gallery/cursor.ts";
import { GenerationError } from "./errors.ts";
import type { GenerationRepository } from "./repository.ts";
import type { CancelGenerationResult, CreateGenerationInput, GenerationPageResult, GenerationStatus, GenerationView, GenerationVisibility, GenerationWorkflowView, PromptVisibility } from "./types.ts";
import { clampToBounds, workflowBounds, workflowSizePresets } from "./workflow-options.ts";

interface WorkflowRow extends QueryResultRow { id: string; slug: string; name: string; description: string; category: string; defaults: Record<string, unknown>; input_schema: unknown }
interface JobRow extends QueryResultRow {
  id: string; status: GenerationStatus; workflow_slug: string; workflow_name: string; requested_width: number; requested_height: number; requested_count: number;
  prompt: string; negative_prompt: string;
  visibility: GenerationVisibility; prompt_visibility: PromptVisibility; credits_reserved: string; credits_charged: string; cancel_requested_at: Date | null;
  created_at: Date; updated_at: Date; finished_at: Date | null; error_code: string | null; error_message: string | null; images: unknown;
}

export class PostgresGenerationRepository implements GenerationRepository {
  readonly #pool: Pool;
  constructor(pool: Pool) { this.#pool = pool; }

  async listWorkflows(defaultCreditCost: string): Promise<readonly GenerationWorkflowView[]> {
    const result = await this.#pool.query<WorkflowRow>(`SELECT w.id, w.slug, w.name, w.description, w.category, v.defaults, v.input_schema
      FROM ai.workflows w JOIN ai.workflow_versions v ON v.workflow_id = w.id AND v.is_active
      WHERE w.is_enabled AND EXISTS (
        SELECT 1 FROM ai.workflow_provider_bindings b JOIN ai.providers p ON p.id = b.provider_id
        WHERE b.workflow_version_id = v.id AND b.is_enabled AND p.status <> 'disabled'
      ) ORDER BY w.sort_order, w.slug`);
    return result.rows.map((row) => workflowView(row, defaultCreditCost));
  }

  async create(input: CreateGenerationInput, defaultCreditCost: string): Promise<GenerationView> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const existing = await this.findByIdempotency(client, input.userId, input.idempotencyKey);
      if (existing) { await client.query("COMMIT"); return existing; }
      const workflowResult = await client.query<WorkflowRow>(`SELECT v.id, w.slug, w.name, w.description, w.category, v.defaults, v.input_schema
        FROM ai.workflows w JOIN ai.workflow_versions v ON v.workflow_id = w.id AND v.is_active
        WHERE w.slug = $1 AND w.is_enabled AND EXISTS (
          SELECT 1 FROM ai.workflow_provider_bindings b JOIN ai.providers p ON p.id = b.provider_id
          WHERE b.workflow_version_id = v.id AND b.is_enabled AND p.status <> 'disabled'
        ) FOR SHARE`, [input.workflowSlug]);
      const workflow = workflowResult.rows[0];
      if (!workflow) throw new GenerationError("workflow_unavailable", "所选创作方式当前不可用。", 409);
      const bounds = workflowBounds(workflow.input_schema);
      if (input.width < bounds.width.min || input.width > bounds.width.max || input.height < bounds.height.min || input.height > bounds.height.max
        || input.count < bounds.count.min || input.count > bounds.count.max) {
        throw new GenerationError("invalid_request", "所选创作方式不支持该画面尺寸或数量，请按选项调整。", 400);
      }
      const cost = (Number(workflowCreditCost(workflow.defaults, defaultCreditCost)) * input.count).toFixed(4);
      const inserted = await client.query<{ id: string }>(`INSERT INTO ai.generation_jobs (
          user_id, workflow_version_id, idempotency_key, prompt, negative_prompt, input_params,
          requested_width, requested_height, requested_count, visibility, prompt_visibility, credits_reserved
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, 0)
        ON CONFLICT (user_id, idempotency_key) WHERE user_id IS NOT NULL AND idempotency_key IS NOT NULL DO NOTHING
        RETURNING id`, [input.userId, workflow.id, input.idempotencyKey, input.prompt, input.negativePrompt, JSON.stringify(input.parameters), input.width, input.height, input.count, input.visibility, input.promptVisibility]);
      const jobId = inserted.rows[0]?.id;
      if (!jobId) {
        const raced = await this.findByIdempotency(client, input.userId, input.idempotencyKey);
        if (!raced) throw new Error("idempotent_generation_missing");
        await client.query("COMMIT");
        return raced;
      }
      if (Number(cost) > 0) await client.query("SELECT * FROM ai.reserve_generation_credits($1, $2, $3, $4)", [input.userId, jobId, cost, `generation-reserve:${jobId}`]);
      await client.query(`INSERT INTO ai.outbox_events (aggregate_type, aggregate_id, event_type, payload)
        VALUES ('generation_job', $1, 'generation.requested', jsonb_build_object('requestId', $2::text))`, [jobId, input.requestId]);
      await client.query(`INSERT INTO ai.audit_logs (request_id, actor_user_id, actor_type, action, resource_type, resource_id, metadata)
        VALUES ($1, $2, 'user', 'generation.create', 'generation_job', $3, jsonb_build_object('workflow', $4::text))`, [input.requestId, input.userId, jobId, input.workflowSlug]);
      const created = await this.findById(client, jobId, input.userId, false);
      if (!created) throw new Error("created_generation_missing");
      await client.query("COMMIT");
      return created;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally { client.release(); }
  }

  findForViewer(id: string, userId: number, isAdmin: boolean): Promise<GenerationView | undefined> { return this.findById(this.#pool, id, userId, isAdmin); }

  async listForViewer(userId: number, cursor: DecodedCursor | undefined, limit: number, status?: GenerationStatus): Promise<GenerationPageResult> {
    const values: unknown[] = [userId, limit + 1];
    const conditions = ["j.user_id = $1"];
    if (status) {
      values.push(status);
      conditions.push(`j.status = $${values.length}`);
    }
    if (cursor) {
      values.push(cursor.at, cursor.id);
      conditions.push(`(j.created_at, j.id) < ($${values.length - 1}::timestamptz, $${values.length}::uuid)`);
    }
    const result = await this.#pool.query<JobRow>(`SELECT j.id, j.status, w.slug AS workflow_slug, w.name AS workflow_name,
        j.prompt, j.negative_prompt, j.requested_width, j.requested_height, j.requested_count,
        j.visibility, j.prompt_visibility, j.credits_reserved, j.credits_charged, j.cancel_requested_at,
        j.created_at, j.updated_at, j.finished_at, j.error_code, j.error_message,
        COALESCE((SELECT jsonb_agg(jsonb_build_object('id', i.id, 'slug', i.slug) ORDER BY i.created_at)
          FROM ai.images i WHERE i.job_id = j.id AND i.deleted_at IS NULL), '[]'::jsonb) AS images
      FROM ai.generation_jobs j JOIN ai.workflow_versions v ON v.id = j.workflow_version_id JOIN ai.workflows w ON w.id = v.workflow_id
      WHERE ${conditions.join(" AND ")}
      ORDER BY j.created_at DESC, j.id DESC
      LIMIT $2`, values);
    const rows = result.rows;
    const hasMore = rows.length > limit;
    const items = hasMore ? rows.slice(0, limit) : rows;
    const last = items[items.length - 1];
    return { items: items.map(jobView), ...(hasMore && last ? { next: { at: last.created_at.toISOString(), id: last.id } } : {}) };
  }

  async requestCancellation(id: string, userId: number, isAdmin: boolean): Promise<CancelGenerationResult | undefined> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const locked = await client.query<{ status: GenerationStatus; user_id: number | null; credits_reserved: string }>("SELECT status, user_id, credits_reserved FROM ai.generation_jobs WHERE id = $1 FOR UPDATE", [id]);
      const job = locked.rows[0];
      if (!job || (!isAdmin && job.user_id !== userId)) { await client.query("ROLLBACK"); return undefined; }
      const terminal = new Set<GenerationStatus>(["completed", "failed", "cancelled"]);
      let accepted = false;
      let signalWorker = false;
      if (!terminal.has(job.status)) {
        accepted = true;
        signalWorker = job.status === "running";
        if (job.status === "pending") {
          await client.query("UPDATE ai.generation_jobs SET status = 'cancelled', cancel_requested_at = now(), finished_at = now() WHERE id = $1", [id]);
          if (Number(job.credits_reserved) > 0) await client.query("SELECT * FROM ai.release_generation_credits($1, $2)", [id, `generation-release:${id}`]);
        } else {
          await client.query("UPDATE ai.generation_jobs SET cancel_requested_at = COALESCE(cancel_requested_at, now()) WHERE id = $1", [id]);
        }
        await client.query(`INSERT INTO ai.audit_logs (actor_user_id, actor_type, action, resource_type, resource_id)
          VALUES ($1, $2, 'generation.cancel_requested', 'generation_job', $3)`, [userId, isAdmin ? "admin" : "user", id]);
      }
      const generation = await this.findById(client, id, userId, isAdmin);
      if (!generation) throw new Error("cancelled_generation_missing");
      await client.query("COMMIT");
      return { generation, accepted, signalWorker };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally { client.release(); }
  }

  private async findByIdempotency(client: PoolClient, userId: number, idempotencyKey: string): Promise<GenerationView | undefined> {
    const result = await client.query<{ id: string }>("SELECT id FROM ai.generation_jobs WHERE user_id = $1 AND idempotency_key = $2", [userId, idempotencyKey]);
    const id = result.rows[0]?.id;
    return id ? this.findById(client, id, userId, false) : undefined;
  }

  private async findById(client: Pick<Pool, "query"> | PoolClient, id: string, userId: number, isAdmin: boolean): Promise<GenerationView | undefined> {
    const result = await client.query<JobRow>(`SELECT j.id, j.status, w.slug AS workflow_slug, w.name AS workflow_name,
        j.prompt, j.negative_prompt, j.requested_width, j.requested_height, j.requested_count, j.visibility, j.prompt_visibility,
        j.credits_reserved, j.credits_charged, j.cancel_requested_at, j.created_at, j.updated_at, j.finished_at,
        j.error_code, j.error_message,
        COALESCE((SELECT jsonb_agg(jsonb_build_object('id', i.id, 'slug', i.slug) ORDER BY i.created_at)
          FROM ai.images i WHERE i.job_id = j.id AND i.deleted_at IS NULL), '[]'::jsonb) AS images
      FROM ai.generation_jobs j JOIN ai.workflow_versions v ON v.id = j.workflow_version_id JOIN ai.workflows w ON w.id = v.workflow_id
      WHERE j.id = $1 AND ($3::boolean OR j.user_id = $2)`, [id, userId, isAdmin]);
    return result.rows[0] ? jobView(result.rows[0]) : undefined;
  }
}

function workflowView(row: WorkflowRow, defaultCreditCost: string): GenerationWorkflowView {
  const bounds = workflowBounds(row.input_schema);
  const defaults = {
    width: boundedInteger(row.defaults.width, 1024, 64, 8192),
    height: boundedInteger(row.defaults.height, 1024, 64, 8192),
    count: boundedInteger(row.defaults.count, 1, 1, 8),
    visibility: visibility(row.defaults.visibility),
  };
  return {
    slug: row.slug, name: row.name, description: row.description, category: row.category,
    defaults: { ...defaults, count: clampToBounds(defaults.count, bounds.count) },
    countRange: { min: bounds.count.min, max: bounds.count.max },
    sizes: workflowSizePresets(bounds, defaults),
    creditCost: workflowCreditCost(row.defaults, defaultCreditCost),
  };
}
function workflowCreditCost(defaults: Record<string, unknown>, fallback: string): string {
  const value = defaults.credit_cost;
  if ((typeof value === "string" || typeof value === "number") && Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 1_000_000) return Number(value).toFixed(4);
  return fallback;
}
function boundedInteger(value: unknown, fallback: number, min: number, max: number): number { return Number.isSafeInteger(value) && Number(value) >= min && Number(value) <= max ? Number(value) : fallback; }
function visibility(value: unknown): GenerationVisibility { return value === "public" || value === "private" ? value : "private"; }
function jobView(row: JobRow): GenerationView {
  const safeMessage = row.error_message?.replace(/[\r\n]/g, " ").slice(0, 240);
  return {
    id: row.id, status: row.status, workflowSlug: row.workflow_slug, workflowName: row.workflow_name,
    prompt: row.prompt, negativePrompt: row.negative_prompt,
    width: row.requested_width, height: row.requested_height, count: row.requested_count,
    visibility: row.visibility, promptVisibility: row.prompt_visibility,
    creditsReserved: row.credits_reserved, creditsCharged: row.credits_charged,
    cancelRequested: row.cancel_requested_at !== null, createdAt: row.created_at.toISOString(), updatedAt: row.updated_at.toISOString(),
    ...(row.finished_at ? { finishedAt: row.finished_at.toISOString() } : {}),
    ...(row.error_code ? { error: { code: row.error_code, message: safeMessage || "生成失败，请稍后重试。" } } : {}),
    images: Array.isArray(row.images) ? row.images.filter(isImageLink) : [],
  };
}
function isImageLink(value: unknown): value is { id: string; slug: string } { return !!value && typeof value === "object" && typeof (value as { id?: unknown }).id === "string" && typeof (value as { slug?: unknown }).slug === "string"; }
