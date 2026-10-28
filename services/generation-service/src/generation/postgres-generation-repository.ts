import type { Pool, PoolClient, QueryResultRow } from "pg";
import type { DecodedCursor } from "../gallery/cursor.ts";
import type { MediaType } from "../providers/types.ts";
import { GenerationError } from "./errors.ts";
import type { GenerationRepository } from "./repository.ts";
import type { CancelGenerationResult, CreateGenerationInput, GenerationMode, GenerationPageResult, GenerationStatus, GenerationView, GenerationVisibility, GenerationWorkflowView, PromptVisibility } from "./types.ts";
import { clampToBounds, workflowBounds, workflowDurationOptions, workflowMediaSizePresets } from "./workflow-options.ts";

interface WorkflowRow extends QueryResultRow { id: string; slug: string; name: string; description: string; category: string; mode: GenerationMode; media_type: MediaType; defaults: Record<string, unknown>; input_schema: unknown }
interface JobRow extends QueryResultRow {
  id: string; status: GenerationStatus; workflow_slug: string; workflow_name: string; requested_width: number; requested_height: number; requested_count: number;
  workflow_mode: GenerationMode; media_type: MediaType;
  prompt: string; negative_prompt: string;
  visibility: GenerationVisibility; prompt_visibility: PromptVisibility; credits_reserved: string; credits_charged: string; cancel_requested_at: Date | null; credit_tier: "free" | "member";
  created_at: Date; updated_at: Date; finished_at: Date | null; error_code: string | null; error_message: string | null; images: unknown; outputs: unknown;
}

export class PostgresGenerationRepository implements GenerationRepository {
  readonly #pool: Pool;
  constructor(pool: Pool) { this.#pool = pool; }

  async listWorkflows(defaultCreditCost: string, mode?: GenerationMode, mediaType?: MediaType): Promise<readonly GenerationWorkflowView[]> {
    const values: unknown[] = [];
    const conditions = ["w.is_enabled", `EXISTS (
        SELECT 1 FROM ai.workflow_provider_bindings b
        JOIN ai.providers p ON p.id = b.provider_id
        LEFT JOIN ai.provider_models m ON m.id = b.provider_model_id AND m.provider_id = p.id
        WHERE b.workflow_version_id = v.id AND b.is_enabled AND p.status <> 'disabled'
          AND (b.provider_model_id IS NULL OR m.is_enabled)
      )`];
    if (mode) {
      values.push(mode);
      conditions.push(`w.mode = $${values.length}`);
    }
    if (mediaType) {
      values.push(mediaType);
      conditions.push(`w.media_type = $${values.length}`);
    }
    const result = await this.#pool.query<WorkflowRow>(`SELECT w.id, w.slug, w.name, w.description, w.category, w.mode, w.media_type, v.defaults, v.input_schema
      FROM ai.workflows w JOIN ai.workflow_versions v ON v.workflow_id = w.id AND v.is_active
      WHERE ${conditions.join(" AND ")}
      ORDER BY w.sort_order, w.slug`, values);
    return result.rows.map((row) => workflowView(row, defaultCreditCost));
  }

  async create(input: CreateGenerationInput, defaultCreditCost: string): Promise<GenerationView> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const existing = await this.findByIdempotency(client, input.userId, input.idempotencyKey);
      if (existing) { await client.query("COMMIT"); return existing; }
      const workflowResult = await client.query<WorkflowRow>(`SELECT v.id, w.slug, w.name, w.description, w.category, w.mode, w.media_type, v.defaults, v.input_schema
        FROM ai.workflows w JOIN ai.workflow_versions v ON v.workflow_id = w.id AND v.is_active
        WHERE w.slug = $1 AND w.is_enabled AND EXISTS (
          SELECT 1 FROM ai.workflow_provider_bindings b JOIN ai.providers p ON p.id = b.provider_id
          LEFT JOIN ai.provider_models m ON m.id = b.provider_model_id AND m.provider_id = p.id
          WHERE b.workflow_version_id = v.id AND b.is_enabled AND p.status <> 'disabled'
            AND (b.provider_model_id IS NULL OR m.is_enabled)
        ) FOR SHARE`, [input.workflowSlug]);
      const workflow = workflowResult.rows[0];
      if (!workflow) throw new GenerationError("workflow_unavailable", "所选创作方式当前不可用。", 409);
      // 参考图模式（mode_meta.maxImages>0，如 H3 单图/多图参考）必须携带
      // 1..maxImages 张参考图：与前端同一约束，防止 API 直调提交空图任务
      // 到 ComfyUI 后才失败、白白消耗积分（此前 parameters.inputImages 由
      // generation-service 上传合并，此处校验数量即可）。
      const requiredImages = parseModeMeta(workflow.defaults.mode_meta).modeMeta;
      if (workflow.media_type === "video" && requiredImages && requiredImages.maxImages > 0) {
        const uploaded = Array.isArray((input.parameters as Record<string, unknown> | undefined)?.inputImages)
          ? ((input.parameters as Record<string, unknown>).inputImages as unknown[]).length
          : 0;
        if (uploaded === 0) throw new GenerationError("invalid_request", "该创作模式需要至少 1 张参考图。", 400);
        if (uploaded > requiredImages.maxImages) throw new GenerationError("invalid_request", `参考图最多 ${requiredImages.maxImages} 张。`, 400);
      }
      const bounds = workflowBounds(workflow.input_schema);
      if (input.width < bounds.width.min || input.width > bounds.width.max || input.height < bounds.height.min || input.height > bounds.height.max
        || input.count < bounds.count.min || input.count > bounds.count.max) {
        throw new GenerationError("invalid_request", "所选创作方式不支持该画面尺寸或数量，请按选项调整。", 400);
      }
      if (workflow.media_type === "video") {
        const fallbackDuration = boundedInteger(workflow.defaults.duration_seconds, 5, 1, 300);
        const allowedDurations = workflowDurationOptions(workflow.input_schema, fallbackDuration);
        const durationSeconds = input.parameters.durationSeconds;
        if (!Number.isSafeInteger(durationSeconds) || !allowedDurations.includes(Number(durationSeconds))) {
          throw new GenerationError("invalid_request", "所选视频工作流不支持该时长，请按选项调整。", 400);
        }
        await client.query("SELECT id FROM public.users WHERE id = $1 FOR UPDATE", [input.userId]);
        const activeVideo = await client.query(`SELECT 1
          FROM ai.generation_jobs j
          JOIN ai.workflow_versions v ON v.id = j.workflow_version_id
          JOIN ai.workflows w ON w.id = v.workflow_id
          WHERE j.user_id = $1 AND w.media_type = 'video' AND j.status IN ('pending','running')
          LIMIT 1`, [input.userId]);
        if (activeVideo.rowCount) throw new GenerationError("video_busy", "已有视频任务正在生成，请等待完成后再创建。", 409);
      }
      const cost = (Number(workflowCreditCostFor(workflow.defaults, defaultCreditCost, input.width, input.height)) * input.count).toFixed(4);
      const inserted = await client.query<{ id: string }>(`INSERT INTO ai.generation_jobs (
          user_id, workflow_version_id, idempotency_key, prompt, negative_prompt, input_params,
          requested_width, requested_height, requested_count, visibility, prompt_visibility, credits_reserved, credit_tier
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, 0, $12)
        ON CONFLICT (user_id, idempotency_key) WHERE user_id IS NOT NULL AND idempotency_key IS NOT NULL DO NOTHING
        RETURNING id`, [input.userId, workflow.id, input.idempotencyKey, input.prompt, input.negativePrompt, JSON.stringify(input.parameters), input.width, input.height, input.count, input.visibility, input.promptVisibility, input.creditTier]);
      const jobId = inserted.rows[0]?.id;
      if (!jobId) {
        const raced = await this.findByIdempotency(client, input.userId, input.idempotencyKey);
        if (!raced) throw new Error("idempotent_generation_missing");
        await client.query("COMMIT");
        return raced;
      }
      if (Number(cost) > 0) {
        const fn = input.creditTier === "member" ? "ai.reserve_member_generation_credits" : "ai.reserve_generation_credits";
        await client.query(`SELECT * FROM ${fn}($1, $2, $3, $4)`, [input.userId, jobId, cost, `generation-reserve:${jobId}`]);
      }
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
    const result = await this.#pool.query<JobRow>(`SELECT j.id, j.status, w.slug AS workflow_slug, w.name AS workflow_name, w.mode AS workflow_mode, w.media_type,
        j.prompt, j.negative_prompt, j.requested_width, j.requested_height, j.requested_count,
        j.visibility, j.prompt_visibility, j.credits_reserved, j.credits_charged, j.credit_tier, j.cancel_requested_at,
        j.created_at, j.updated_at, j.finished_at, j.error_code, j.error_message,
        COALESCE((SELECT jsonb_agg(jsonb_build_object('id', i.id, 'slug', i.slug) ORDER BY i.created_at)
          FROM ai.images i WHERE i.job_id = j.id AND i.deleted_at IS NULL), '[]'::jsonb) AS images,
        COALESCE((SELECT jsonb_agg(jsonb_build_object('id', a.id, 'mediaType', a.media_type, 'url', a.asset_url,
          'mimeType', a.mime_type, 'width', a.width, 'height', a.height, 'durationSeconds', a.duration_seconds) ORDER BY a.position)
          FROM ai.generation_assets a WHERE a.job_id = j.id), '[]'::jsonb) AS outputs
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
      const locked = await client.query<{ status: GenerationStatus; user_id: number | null; credits_reserved: string; credit_tier: "free" | "member"; media_type: MediaType }>(`SELECT j.status, j.user_id, j.credits_reserved, j.credit_tier, w.media_type
        FROM ai.generation_jobs j JOIN ai.workflow_versions v ON v.id = j.workflow_version_id JOIN ai.workflows w ON w.id = v.workflow_id
        WHERE j.id = $1 FOR UPDATE OF j`, [id]);
      const job = locked.rows[0];
      if (!job || (!isAdmin && job.user_id !== userId)) { await client.query("ROLLBACK"); return undefined; }
      const terminal = new Set<GenerationStatus>(["completed", "failed", "cancelled"]);
      let accepted = false;
      let signalWorker = false;
      // Running video providers may reject cancellation while still billing
      // the upstream task. Only queued video work is user-cancellable so a
      // refund can never race with an unavoidable provider charge.
      if (!terminal.has(job.status) && !(job.media_type === "video" && job.status === "running")) {
        accepted = true;
        // Pending jobs still have a BullMQ entry. Let the queue adapter remove
        // it first, then settle this row through finalizeCancellation; marking
        // it terminal before removal leaves an orphaned queue job and makes a
        // removed cancellation unable to release the reservation reliably.
        signalWorker = true;
        await client.query("UPDATE ai.generation_jobs SET cancel_requested_at = COALESCE(cancel_requested_at, now()) WHERE id = $1", [id]);
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

  async finalizeCancellation(id: string, userId: number, isAdmin: boolean): Promise<GenerationView | undefined> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const locked = await client.query<{ status: GenerationStatus; user_id: number | null; credits_reserved: string; credit_tier: "free" | "member" }>("SELECT status, user_id, credits_reserved, credit_tier FROM ai.generation_jobs WHERE id = $1 FOR UPDATE", [id]);
      const job = locked.rows[0];
      if (!job || (!isAdmin && job.user_id !== userId)) { await client.query("ROLLBACK"); return undefined; }
      if (job.status === "running" || job.status === "pending") {
        await client.query("UPDATE ai.generation_jobs SET status = 'cancelled', cancel_requested_at = COALESCE(cancel_requested_at, now()), finished_at = now() WHERE id = $1", [id]);
        if (Number(job.credits_reserved) > 0) await releaseCreditsById(client, id, job.credit_tier, `generation-release:${id}`);
        await client.query("INSERT INTO ai.audit_logs (actor_user_id, actor_type, action, resource_type, resource_id) VALUES ($1, $2, 'generation.cancelled', 'generation_job', $3)", [userId, isAdmin ? "admin" : "user", id]);
      }
      const generation = await this.findById(client, id, userId, isAdmin);
      if (!generation) throw new Error("cancelled_generation_missing");
      await client.query("COMMIT");
      return generation;
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
    const result = await client.query<JobRow>(`SELECT j.id, j.status, w.slug AS workflow_slug, w.name AS workflow_name, w.mode AS workflow_mode, w.media_type,
        j.prompt, j.negative_prompt, j.requested_width, j.requested_height, j.requested_count, j.visibility, j.prompt_visibility,
        j.credits_reserved, j.credits_charged, j.credit_tier, j.cancel_requested_at, j.created_at, j.updated_at, j.finished_at,
        j.error_code, j.error_message,
        COALESCE((SELECT jsonb_agg(jsonb_build_object('id', i.id, 'slug', i.slug) ORDER BY i.created_at)
          FROM ai.images i WHERE i.job_id = j.id AND i.deleted_at IS NULL), '[]'::jsonb) AS images,
        COALESCE((SELECT jsonb_agg(jsonb_build_object('id', a.id, 'mediaType', a.media_type, 'url', a.asset_url,
          'mimeType', a.mime_type, 'width', a.width, 'height', a.height, 'durationSeconds', a.duration_seconds) ORDER BY a.position)
          FROM ai.generation_assets a WHERE a.job_id = j.id), '[]'::jsonb) AS outputs
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
    visibility: visibility(row.defaults.visibility, "public"),
    promptVisibility: promptVisibility(row.defaults.prompt_visibility, "public"),
    ...(row.media_type === "video" ? { durationSeconds: boundedInteger(row.defaults.duration_seconds, 5, 1, 300) } : {}),
  };
  return {
    slug: row.slug, name: row.name, description: row.description, category: row.category,
    mode: row.mode === "api" ? "api" : "workflow", mediaType: row.media_type,
    defaults: {
      ...defaults,
      count: clampToBounds(defaults.count, bounds.count),
      // mode_meta 驱动前端"单图/多图参考"模式页签与参考图上传入口（maxImages>0
      // 才渲染上传 UI）；videoResolutions 驱动分辨率下拉。两者来自迁移写入的
      // defaults JSONB，解析失败时降级省略（前端 fallback 到默认 UI），绝不影响列表接口可用性。
      ...parseModeMeta(row.defaults.mode_meta),
      ...parseVideoResolutions(row.defaults.videoResolutions),
    },
    countRange: { min: bounds.count.min, max: bounds.count.max },
    sizes: workflowMediaSizePresets(bounds, defaults, row.media_type),
    durations: row.media_type === "video" ? workflowDurationOptions(row.input_schema, defaults.durationSeconds ?? 5) : [],
    creditCost: workflowCreditCost(row.defaults, defaultCreditCost),
  };
}
/** 校验并透传 defaults.mode_meta（迁移 0019 写入）：结构非法时返回空对象，由前端 fallback。 */
function parseModeMeta(value: unknown): { modeMeta?: { readonly key: string; readonly label: string; readonly maxImages: number } } {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const meta = value as Record<string, unknown>;
  const key = typeof meta.key === "string" && meta.key.trim() ? meta.key.trim() : undefined;
  const label = typeof meta.label === "string" && meta.label.trim() ? meta.label.trim() : undefined;
  const maxImages = Number(meta.maxImages);
  if (!key || !label || !Number.isSafeInteger(maxImages) || maxImages < 0 || maxImages > 3) return {};
  return { modeMeta: { key, label, maxImages } };
}
/** 校验并透传 defaults.videoResolutions（迁移 0021 写入）：至少一档合法才透传，否则由前端 fallback 默认档。 */
function parseVideoResolutions(value: unknown): { videoResolutions?: readonly { readonly key: string; readonly label: string; readonly height: number }[] } {
  if (!Array.isArray(value) || value.length === 0) return {};
  const entries: { key: string; label: string; height: number }[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const entry = item as Record<string, unknown>;
    const key = typeof entry.key === "string" && entry.key.trim() ? entry.key.trim() : undefined;
    const label = typeof entry.label === "string" && entry.label.trim() ? entry.label.trim() : undefined;
    const height = Number(entry.height);
    if (!key || !label || !Number.isSafeInteger(height) || height < 120 || height > 2160) continue;
    entries.push({ key, label, height });
  }
  return entries.length > 0 ? { videoResolutions: entries } : {};
}
function workflowCreditCost(defaults: Record<string, unknown>, fallback: string): string {
  const value = defaults.credit_cost;
  if ((typeof value === "string" || typeof value === "number") && Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 1_000_000) return Number(value).toFixed(4);
  return fallback;
}
function workflowCreditCostFor(defaults: Record<string, unknown>, fallback: string, width: number, height: number): string {
  const pricing = defaults.pricing;
  if (pricing && typeof pricing === "object" && !Array.isArray(pricing)) {
    const value = (pricing as Record<string, unknown>)[`${width}x${height}`];
    if ((typeof value === "string" || typeof value === "number") && Number.isFinite(Number(value)) && Number(value) >= 0) {
      return Number(value).toFixed(4);
    }
  }
  return workflowCreditCost(defaults, fallback);
}
function boundedInteger(value: unknown, fallback: number, min: number, max: number): number { return Number.isSafeInteger(value) && Number(value) >= min && Number(value) <= max ? Number(value) : fallback; }
function visibility(value: unknown, fallback: GenerationVisibility): GenerationVisibility { return value === "public" || value === "private" ? value : fallback; }
function promptVisibility(value: unknown, fallback: PromptVisibility): PromptVisibility { return value === "public" || value === "hidden" ? value : fallback; }
function jobView(row: JobRow): GenerationView {
  const safeMessage = row.error_message?.replace(/[\r\n]/g, " ").slice(0, 240);
  return {
    id: row.id, status: row.status, workflowSlug: row.workflow_slug, workflowName: row.workflow_name, mediaType: row.media_type,
    mode: row.workflow_mode === "api" ? "api" : "workflow",
    prompt: row.prompt, negativePrompt: row.negative_prompt,
    width: row.requested_width, height: row.requested_height, count: row.requested_count,
    visibility: row.visibility, promptVisibility: row.prompt_visibility,
    creditsReserved: row.credits_reserved, creditsCharged: row.credits_charged,
    creditTier: row.credit_tier,
    cancelRequested: row.cancel_requested_at !== null, createdAt: row.created_at.toISOString(), updatedAt: row.updated_at.toISOString(),
    ...(row.finished_at ? { finishedAt: row.finished_at.toISOString() } : {}),
    ...(row.error_code ? { error: { code: row.error_code, message: safeMessage || "生成失败，请稍后重试。" } } : {}),
    images: Array.isArray(row.images) ? row.images.filter(isImageLink) : [],
    outputs: Array.isArray(row.outputs) ? row.outputs.filter(isGenerationOutput) : [],
  };
}
function isImageLink(value: unknown): value is { id: string; slug: string } { return !!value && typeof value === "object" && typeof (value as { id?: unknown }).id === "string" && typeof (value as { slug?: unknown }).slug === "string"; }
function isGenerationOutput(value: unknown): value is GenerationView["outputs"][number] {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === "string" && (item.mediaType === "image" || item.mediaType === "video") && typeof item.url === "string"
    && typeof item.mimeType === "string" && Number.isFinite(Number(item.width)) && Number.isFinite(Number(item.height));
}
async function releaseCreditsById(client: PoolClient, jobId: string, creditTier: "free" | "member", idempotency: string): Promise<void> {
  const fn = creditTier === "member" ? "ai.release_member_generation_credits" : "ai.release_generation_credits";
  await client.query(`SELECT * FROM ${fn}($1, $2)`, [jobId, idempotency]);
}
