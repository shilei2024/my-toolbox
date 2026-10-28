import type { Pool, PoolClient, QueryResultRow } from "pg";
import type { GalleryAssetRecord, GalleryAssetUrlResolver } from "../gallery/asset-url.ts";
import { GalleryError } from "../gallery/errors.ts";
import type { AdminRepository } from "./repository.ts";
import type { AdminAuditItem, AdminCuratedImageItem, AdminDashboard, AdminImageItem, AdminJobItem, AdminOverview, AdminProviderItem, AdminProviderModelItem, AdminWorkflowItem, CreateCuratedImageCommand, ModerateImageCommand, UpdateCuratedImageCommand, UpdateProviderCommand, UpdateProviderModelCommand, UpdateWorkflowCommand } from "./types.ts";

interface CountRow extends QueryResultRow {
  pending_moderation: string;
  public_images: string;
  jobs_last_24_hours: string;
  failed_jobs_last_24_hours: string;
  active_providers: string;
  enabled_workflows: string;
}

interface ImageRow extends QueryResultRow {
  id: string;
  slug: string;
  title: string;
  workflow_name_snapshot: string;
  media_type: "image" | "video";
  moderation_status: AdminImageItem["moderationStatus"];
  visibility: AdminImageItem["visibility"];
  prompt_visibility: AdminImageItem["promptVisibility"];
  created_at: Date | string;
  updated_at: Date | string;
  asset_storage_provider: string;
  asset_bucket: string;
  asset_region: string;
  asset_object_key: string;
  asset_public_url: string | null;
}

interface ProviderRow extends QueryResultRow {
  id: string;
  code: string;
  display_name: string;
  adapter_type: string;
  status: AdminProviderItem["status"];
  priority: number;
  secret_ref: string | null;
  consecutive_failures: number;
  last_health_at: Date | string | null;
  updated_at: Date | string;
}

interface ProviderModelRow extends QueryResultRow {
  id: string;
  provider_id: string;
  model_code: string;
  display_name: string;
  tier: "free" | "member";
  credit_cost: string | null;
  is_default: boolean;
  is_enabled: boolean;
  updated_at: Date | string;
}

interface WorkflowRow extends QueryResultRow {
  id: string;
  slug: string;
  name: string;
  category: string;
  mode: "workflow" | "api";
  is_enabled: boolean;
  sort_order: number;
  active_version: number | null;
  binding_count: string;
  updated_at: Date | string;
}

interface JobRow extends QueryResultRow {
  id: string;
  status: AdminJobItem["status"];
  workflow_name: string;
  provider_code: string | null;
  actual_cost: string;
  created_at: Date | string;
  finished_at: Date | string | null;
}

interface AuditRow extends QueryResultRow {
  id: string;
  actor_user_id: number | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  created_at: Date | string;
}

interface CuratedRow extends QueryResultRow {
  id: string;
  slug: string;
  title: string;
  description: string;
  prompt: string;
  negative_prompt: string;
  model_snapshot: string | null;
  workflow_name_snapshot: string;
  width: number;
  height: number;
  media_type: "image" | "video";
  prompt_visibility: "public" | "hidden";
  published_at: Date | string | null;
  created_at: Date | string;
  updated_at: Date | string;
  tags: string[] | null;
  asset_storage_provider: string;
  asset_bucket: string;
  asset_region: string;
  asset_object_key: string;
  asset_public_url: string | null;
}

export class PostgresAdminRepository implements AdminRepository {
  readonly #pool: Pool;
  readonly #assets: GalleryAssetUrlResolver;

  constructor(pool: Pool, assets: GalleryAssetUrlResolver) {
    this.#pool = pool;
    this.#assets = assets;
  }

  async dashboard(): Promise<AdminDashboard> {
    const [counts, images, providers, modelRows, workflows, jobs, audit] = await Promise.all([
      this.#pool.query<CountRow>(`SELECT
        (SELECT count(*) FROM ai.images WHERE moderation_status IN ('pending', 'manual_review') AND deleted_at IS NULL) AS pending_moderation,
        (SELECT count(*) FROM ai.images WHERE visibility = 'public' AND moderation_status = 'approved' AND deleted_at IS NULL) AS public_images,
        (SELECT count(*) FROM ai.generation_jobs WHERE created_at >= now() - interval '24 hours') AS jobs_last_24_hours,
        (SELECT count(*) FROM ai.generation_jobs WHERE status = 'failed' AND created_at >= now() - interval '24 hours') AS failed_jobs_last_24_hours,
        (SELECT count(*) FROM ai.providers WHERE status = 'active') AS active_providers,
        (SELECT count(*) FROM ai.workflows WHERE is_enabled) AS enabled_workflows`),
      this.#pool.query<ImageRow>(`${imageSelect()} WHERE i.moderation_status IN ('pending', 'manual_review') AND i.deleted_at IS NULL ORDER BY i.created_at ASC, i.id ASC LIMIT 40`),
      this.#pool.query<ProviderRow>(`SELECT id, code, display_name, adapter_type, status, priority, secret_ref, consecutive_failures, last_health_at, updated_at FROM ai.providers ORDER BY priority ASC, code ASC LIMIT 100`),
      this.#pool.query<ProviderModelRow>(`SELECT id, provider_id, model_code, display_name, tier, credit_cost, is_default, is_enabled, updated_at
        FROM ai.provider_models ORDER BY provider_id, is_default DESC, model_code ASC LIMIT 500`),
      this.#pool.query<WorkflowRow>(workflowSelect("ORDER BY w.sort_order ASC, w.slug ASC LIMIT 100")),
      this.#pool.query<JobRow>(`SELECT j.id, j.status, w.name AS workflow_name, p.code AS provider_code, j.actual_cost, j.created_at, j.finished_at
        FROM ai.generation_jobs j JOIN ai.workflow_versions v ON v.id = j.workflow_version_id JOIN ai.workflows w ON w.id = v.workflow_id
        LEFT JOIN ai.providers p ON p.id = j.selected_provider_id ORDER BY j.created_at DESC LIMIT 20`),
      this.#pool.query<AuditRow>(`SELECT id::text, actor_user_id, action, resource_type, resource_id, created_at FROM ai.audit_logs WHERE actor_type = 'admin' ORDER BY created_at DESC, id DESC LIMIT 30`),
    ]);
    const row = counts.rows[0];
    const modelsByProvider = new Map<string, AdminProviderModelItem[]>();
    for (const modelRow of modelRows.rows) {
      const list = modelsByProvider.get(modelRow.provider_id) ?? [];
      list.push(model(modelRow));
      modelsByProvider.set(modelRow.provider_id, list);
    }
    const overview: AdminOverview = {
      pendingModeration: Number(row?.pending_moderation ?? 0),
      publicImages: Number(row?.public_images ?? 0),
      jobsLast24Hours: Number(row?.jobs_last_24_hours ?? 0),
      failedJobsLast24Hours: Number(row?.failed_jobs_last_24_hours ?? 0),
      activeProviders: Number(row?.active_providers ?? 0),
      enabledWorkflows: Number(row?.enabled_workflows ?? 0),
    };
    return {
      overview,
      moderationQueue: await Promise.all(images.rows.map((item) => this.image(item))),
      providers: providers.rows.map((item) => provider(item, modelsByProvider.get(item.id) ?? [])),
      workflows: workflows.rows.map(workflow),
      recentJobs: jobs.rows.map(job),
      recentAudit: audit.rows.map(auditItem),
    };
  }

  async moderateImage(imageId: string, command: ModerateImageCommand, adminUserId: number, requestId: string): Promise<AdminImageItem> {
    const row = await this.transaction(async (client) => {
      const current = await client.query<{ moderation_status: string; updated_at: Date | string }>("SELECT moderation_status, updated_at FROM ai.images WHERE id = $1 AND deleted_at IS NULL FOR UPDATE", [imageId]);
      if (!current.rows[0]) throw notFound("Image was not found");
      if (iso(current.rows[0].updated_at) !== command.expectedUpdatedAt) throw conflict();
      const updated = await client.query<ImageRow>(`${imageSelect()} WHERE i.id = $1`, [imageId]);
      await client.query(`UPDATE ai.images SET moderation_status = $2::ai.moderation_status,
          published_at = CASE WHEN $2::ai.moderation_status = 'approved' AND visibility = 'public' THEN COALESCE(published_at, now()) ELSE NULL END
        WHERE id = $1`, [imageId, command.decision]);
      await client.query(`INSERT INTO ai.moderation_events (image_id, stage, decision, reason_codes, reviewer_user_id)
        VALUES ($1, 'manual', $2, $3::jsonb, $4)`, [imageId, command.decision, JSON.stringify(command.reasonCodes), adminUserId]);
      await insertAudit(client, requestId, adminUserId, "admin.image_moderated", "image", imageId, { from: current.rows[0].moderation_status, to: command.decision, reasonCodes: command.reasonCodes });
      const result = await client.query<ImageRow>(`${imageSelect()} WHERE i.id = $1`, [imageId]);
      return result.rows[0] ?? updated.rows[0]!;
    });
    return this.image(row);
  }

  async updateProvider(providerId: string, command: UpdateProviderCommand, adminUserId: number, requestId: string): Promise<AdminProviderItem> {
    const row = await this.transaction(async (client) => {
      const current = await client.query<ProviderRow>("SELECT id, code, display_name, adapter_type, status, priority, secret_ref, consecutive_failures, last_health_at, updated_at FROM ai.providers WHERE id = $1 FOR UPDATE", [providerId]);
      if (!current.rows[0]) throw notFound("Provider was not found");
      if (iso(current.rows[0].updated_at) !== command.expectedUpdatedAt) throw conflict();
      const result = await client.query<ProviderRow>(`UPDATE ai.providers SET status = $2, priority = $3 WHERE id = $1
        RETURNING id, code, display_name, adapter_type, status, priority, secret_ref, consecutive_failures, last_health_at, updated_at`, [providerId, command.status, command.priority]);
      await insertAudit(client, requestId, adminUserId, "admin.provider_updated", "provider", providerId, { from: { status: current.rows[0].status, priority: current.rows[0].priority }, to: { status: command.status, priority: command.priority } });
      return result.rows[0]!;
    });
    return provider(row, []);
  }

  async updateProviderModel(modelId: string, command: UpdateProviderModelCommand, adminUserId: number, requestId: string): Promise<AdminProviderModelItem> {
    const row = await this.transaction(async (client) => {
      const current = await client.query<ProviderModelRow>(
        "SELECT id, provider_id, model_code, display_name, tier, credit_cost, is_default, is_enabled, updated_at FROM ai.provider_models WHERE id = $1 FOR UPDATE",
        [modelId],
      );
      if (!current.rows[0]) throw notFound("Provider model was not found");
      if (iso(current.rows[0].updated_at) !== command.expectedUpdatedAt) throw conflict();
      if (command.isDefault) {
        await client.query("UPDATE ai.provider_models SET is_default = false WHERE provider_id = $1 AND id <> $2", [current.rows[0].provider_id, modelId]);
      }
      const result = await client.query<ProviderModelRow>(
        `UPDATE ai.provider_models SET tier = $2, credit_cost = $3, is_default = $4, is_enabled = $5 WHERE id = $1
         RETURNING id, provider_id, model_code, display_name, tier, credit_cost, is_default, is_enabled, updated_at`,
        [modelId, command.tier, command.creditCost === undefined ? null : command.creditCost, command.isDefault, command.isEnabled],
      );
      await insertAudit(client, requestId, adminUserId, "admin.provider_model_updated", "provider_model", modelId, {
        from: { tier: current.rows[0].tier, creditCost: current.rows[0].credit_cost, isDefault: current.rows[0].is_default, isEnabled: current.rows[0].is_enabled },
        to: { tier: command.tier, creditCost: command.creditCost ?? null, isDefault: command.isDefault, isEnabled: command.isEnabled },
      });
      return result.rows[0]!;
    });
    return model(row);
  }

  async updateWorkflow(workflowId: string, command: UpdateWorkflowCommand, adminUserId: number, requestId: string): Promise<AdminWorkflowItem> {
    const row = await this.transaction(async (client) => {
      const current = await client.query<{ is_enabled: boolean; sort_order: number; updated_at: Date | string }>("SELECT is_enabled, sort_order, updated_at FROM ai.workflows WHERE id = $1 FOR UPDATE", [workflowId]);
      if (!current.rows[0]) throw notFound("Workflow was not found");
      if (iso(current.rows[0].updated_at) !== command.expectedUpdatedAt) throw conflict();
      await client.query("UPDATE ai.workflows SET is_enabled = $2, sort_order = $3 WHERE id = $1", [workflowId, command.isEnabled, command.sortOrder]);
      await insertAudit(client, requestId, adminUserId, "admin.workflow_updated", "workflow", workflowId, { from: { isEnabled: current.rows[0].is_enabled, sortOrder: current.rows[0].sort_order }, to: { isEnabled: command.isEnabled, sortOrder: command.sortOrder } });
      const result = await client.query<WorkflowRow>(workflowSelect("WHERE w.id = $1"), [workflowId]);
      return result.rows[0]!;
    });
    return workflow(row);
  }

  /* -------- 策展作品 -------- */

  async createCuratedImage(command: CreateCuratedImageCommand, adminUserId: number, requestId: string): Promise<AdminCuratedImageItem> {
    const row = await this.transaction(async (client) => {
      const original = command.assets.find((asset) => asset.variant === "original");
      if (!original) throw invalid("Curated image requires an original asset");
      const image = await client.query<{ id: string }>(`INSERT INTO ai.images (
          slug, title, description, prompt, negative_prompt,
          provider_code_snapshot, model_snapshot, workflow_name_snapshot,
          width, height, creator_user_id, curated_by_user_id, origin,
          visibility, prompt_visibility, moderation_status, published_at
        ) VALUES ($1, $2, $3, $4, $5, 'curated', $6, $6, $7, $8, NULL, $9, 'curated',
          'public', $10::ai.prompt_visibility, 'approved', now())
        RETURNING id`,
      [command.slug, command.title, command.description, command.prompt, command.negativePrompt,
        command.model, command.width, command.height, adminUserId, command.promptVisibility]);
      const imageId = image.rows[0]!.id;
      for (const asset of command.assets) {
        await client.query(`INSERT INTO ai.image_assets (image_id, variant, storage_provider, bucket, region, object_key, public_url, mime_type, byte_size, width, height, sha256)
          VALUES ($1, $2::ai.asset_variant, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
          ON CONFLICT (image_id, variant) DO NOTHING`,
        [imageId, asset.variant, asset.storageProvider, asset.bucket, asset.region, asset.objectKey, asset.publicUrl ?? null,
          asset.mimeType, asset.byteSize, asset.width, asset.height, asset.sha256]);
      }
      await replaceTags(client, imageId, command.tags);
      await insertAudit(client, requestId, adminUserId, "admin.curated_image_created", "image", imageId, {
        slug: command.slug, model: command.model, promptLength: command.prompt.length, tags: command.tags,
      });
      const created = await client.query<CuratedRow>(`${curatedSelect()} WHERE i.id = $1`, [imageId]);
      return created.rows[0]!;
    });
    return this.curated(row);
  }

  async updateCuratedImage(imageId: string, command: UpdateCuratedImageCommand, adminUserId: number, requestId: string): Promise<AdminCuratedImageItem> {
    const row = await this.transaction(async (client) => {
      const current = await client.query("SELECT 1 FROM ai.images WHERE id = $1 AND origin = 'curated' AND deleted_at IS NULL FOR UPDATE", [imageId]);
      if (!current.rows[0]) throw notFound("Curated image was not found");
      const values: unknown[] = [imageId];
      const sets: string[] = [];
      const assign = (column: string, value: unknown): void => { values.push(value); sets.push(`${column} = $${values.length}`); };
      if (command.title !== undefined) assign("title", command.title);
      if (command.description !== undefined) assign("description", command.description);
      if (command.prompt !== undefined) assign("prompt", command.prompt);
      if (command.negativePrompt !== undefined) assign("negative_prompt", command.negativePrompt);
      if (command.model !== undefined) { assign("model_snapshot", command.model); assign("workflow_name_snapshot", command.model); }
      if (command.promptVisibility !== undefined) { values.push(command.promptVisibility); sets.push(`prompt_visibility = $${values.length}::ai.prompt_visibility`); }
      if (sets.length > 0) await client.query(`UPDATE ai.images SET ${sets.join(", ")} WHERE id = $1`, values);
      if (command.tags !== undefined) await replaceTags(client, imageId, command.tags);
      await insertAudit(client, requestId, adminUserId, "admin.curated_image_updated", "image", imageId, { fields: Object.keys(command) });
      const updated = await client.query<CuratedRow>(`${curatedSelect()} WHERE i.id = $1`, [imageId]);
      return updated.rows[0]!;
    });
    return this.curated(row);
  }

  async listCuratedImages(limit: number): Promise<readonly AdminCuratedImageItem[]> {
    const result = await this.#pool.query<CuratedRow>(`${curatedSelect()}
      WHERE i.origin = 'curated' AND i.deleted_at IS NULL
      ORDER BY i.created_at DESC, i.id DESC
      LIMIT $1`, [limit]);
    return Promise.all(result.rows.map((row) => this.curated(row)));
  }

  async deleteCuratedImage(imageId: string, adminUserId: number, requestId: string, retentionSeconds: number): Promise<{ readonly slug: string }> {
    return this.transaction(async (client) => {
      const deleted = await client.query<{ slug: string }>(`UPDATE ai.images SET deleted_at = now()
        WHERE id = $1 AND origin = 'curated' AND deleted_at IS NULL RETURNING slug`, [imageId]);
      const row = deleted.rows[0];
      if (!row) throw notFound("Curated image was not found");
      await client.query(`INSERT INTO ai.asset_deletion_tasks (image_id, available_at)
        VALUES ($1, now() + ($2 * interval '1 second'))
        ON CONFLICT (image_id) DO UPDATE SET status = 'pending', available_at = EXCLUDED.available_at, last_error = NULL`, [imageId, retentionSeconds]);
      await insertAudit(client, requestId, adminUserId, "admin.curated_image_deleted", "image", imageId, { slug: row.slug, retentionSeconds });
      return row;
    });
  }

  private async curated(row: CuratedRow): Promise<AdminCuratedImageItem> {
    const asset: GalleryAssetRecord = {
      storageProvider: row.asset_storage_provider,
      bucket: row.asset_bucket,
      region: row.asset_region,
      objectKey: row.asset_object_key,
      ...(row.asset_public_url ? { publicUrl: row.asset_public_url } : {}),
    };
    return {
      id: row.id,
      slug: row.slug,
      title: row.title,
      description: row.description,
      prompt: row.prompt,
      negativePrompt: row.negative_prompt,
      model: row.model_snapshot ?? row.workflow_name_snapshot,
      tags: row.tags ?? [],
      width: row.width,
      height: row.height,
      mediaType: row.media_type === "video" ? "video" : "image",
      promptVisibility: row.prompt_visibility,
      thumbnailUrl: await this.#assets.resolve(asset, true),
      ...(row.published_at ? { publishedAt: iso(row.published_at) } : {}),
      createdAt: iso(row.created_at),
      updatedAt: iso(row.updated_at),
    };
  }

  private async image(row: ImageRow): Promise<AdminImageItem> {
    const asset: GalleryAssetRecord = {
      storageProvider: row.asset_storage_provider,
      bucket: row.asset_bucket,
      region: row.asset_region,
      objectKey: row.asset_object_key,
      ...(row.asset_public_url ? { publicUrl: row.asset_public_url } : {}),
    };
    return { id: row.id, slug: row.slug, title: row.title, workflowName: row.workflow_name_snapshot, mediaType: row.media_type === "video" ? "video" : "image", moderationStatus: row.moderation_status, visibility: row.visibility, promptVisibility: row.prompt_visibility, thumbnailUrl: await this.#assets.resolve(asset, false), createdAt: iso(row.created_at), updatedAt: iso(row.updated_at) };
  }

  private async transaction<T>(work: (client: PoolClient) => Promise<T>): Promise<T> {
    const client = await this.#pool.connect();
    try { await client.query("BEGIN"); const result = await work(client); await client.query("COMMIT"); return result; }
    catch (error) { await client.query("ROLLBACK"); throw error; }
    finally { client.release(); }
  }
}

function imageSelect(): string {
  return `SELECT i.id, i.slug, i.title, i.workflow_name_snapshot, i.media_type, i.moderation_status, i.visibility, i.prompt_visibility, i.created_at, i.updated_at,
      asset.storage_provider AS asset_storage_provider, asset.bucket AS asset_bucket, asset.region AS asset_region,
      asset.object_key AS asset_object_key, asset.public_url AS asset_public_url
    FROM ai.images i JOIN LATERAL (
      SELECT selected.* FROM ai.image_assets selected WHERE selected.image_id = i.id
      ORDER BY CASE selected.variant WHEN 'thumbnail' THEN 0 WHEN 'preview' THEN 1 ELSE 2 END LIMIT 1
    ) asset ON true`;
}

function workflowSelect(suffix: string): string {
  return `SELECT w.id, w.slug, w.name, w.category, w.mode, w.is_enabled, w.sort_order, w.updated_at,
      active.version AS active_version, COALESCE(binding.binding_count, 0)::text AS binding_count
    FROM ai.workflows w
    LEFT JOIN LATERAL (SELECT version FROM ai.workflow_versions WHERE workflow_id = w.id AND is_active LIMIT 1) active ON true
    LEFT JOIN LATERAL (SELECT count(*) AS binding_count FROM ai.workflow_versions v JOIN ai.workflow_provider_bindings b ON b.workflow_version_id = v.id WHERE v.workflow_id = w.id AND b.is_enabled) binding ON true
    ${suffix}`;
}

function provider(row: ProviderRow, models: readonly AdminProviderModelItem[]): AdminProviderItem {
  return { id: row.id, code: row.code, displayName: row.display_name, adapterType: row.adapter_type, status: row.status, priority: row.priority, secretConfigured: !!row.secret_ref, consecutiveFailures: row.consecutive_failures, ...(row.last_health_at ? { lastHealthAt: iso(row.last_health_at) } : {}), updatedAt: iso(row.updated_at), models };
}

function model(row: ProviderModelRow): AdminProviderModelItem {
  return {
    id: row.id,
    providerId: row.provider_id,
    modelCode: row.model_code,
    displayName: row.display_name,
    tier: row.tier,
    ...(row.credit_cost === null ? {} : { creditCost: Number(row.credit_cost) }),
    isDefault: row.is_default,
    isEnabled: row.is_enabled,
    updatedAt: iso(row.updated_at),
  };
}

function workflow(row: WorkflowRow): AdminWorkflowItem {
  return { id: row.id, slug: row.slug, name: row.name, category: row.category, mode: row.mode === "api" ? "api" : "workflow", isEnabled: row.is_enabled, sortOrder: row.sort_order, ...(row.active_version !== null ? { activeVersion: row.active_version } : {}), bindingCount: Number(row.binding_count), updatedAt: iso(row.updated_at) };
}

function job(row: JobRow): AdminJobItem {
  return { id: row.id, status: row.status, workflowName: row.workflow_name, ...(row.provider_code ? { providerCode: row.provider_code } : {}), actualCost: Number(row.actual_cost), createdAt: iso(row.created_at), ...(row.finished_at ? { finishedAt: iso(row.finished_at) } : {}) };
}

function auditItem(row: AuditRow): AdminAuditItem {
  return { id: row.id, ...(row.actor_user_id ? { actorUserId: row.actor_user_id } : {}), action: row.action, resourceType: row.resource_type, ...(row.resource_id ? { resourceId: row.resource_id } : {}), createdAt: iso(row.created_at) };
}

async function insertAudit(client: PoolClient, requestId: string, adminUserId: number, action: string, resourceType: string, resourceId: string, metadata: Record<string, unknown>): Promise<void> {
  await client.query(`INSERT INTO ai.audit_logs (request_id, actor_user_id, actor_type, action, resource_type, resource_id, metadata)
    VALUES ($1::uuid, $2, 'admin', $3, $4, $5, $6::jsonb)`, [requestId, adminUserId, action, resourceType, resourceId, JSON.stringify(metadata)]);
}

function iso(value: Date | string): string { return (value instanceof Date ? value : new Date(value)).toISOString(); }
function notFound(message: string): GalleryError { return new GalleryError("resource_not_found", message, 404); }
function conflict(): GalleryError { return new GalleryError("conflict", "The resource changed; refresh before retrying", 409); }
function invalid(message: string): GalleryError { return new GalleryError("invalid_request", message, 400); }

/** 策展作品列表/回读：缩略图优先，附带标签聚合。 */
function curatedSelect(): string {
  return `SELECT i.id, i.slug, i.title, i.description, i.prompt, i.negative_prompt, i.model_snapshot, i.workflow_name_snapshot,
      i.width, i.height, i.media_type, i.prompt_visibility, i.published_at, i.created_at, i.updated_at,
      COALESCE(tag_list.tags, ARRAY[]::text[]) AS tags,
      asset.storage_provider AS asset_storage_provider, asset.bucket AS asset_bucket, asset.region AS asset_region,
      asset.object_key AS asset_object_key, asset.public_url AS asset_public_url
    FROM ai.images i
    JOIN LATERAL (
      SELECT selected.* FROM ai.image_assets selected WHERE selected.image_id = i.id
      ORDER BY CASE selected.variant WHEN 'thumbnail' THEN 0 WHEN 'preview' THEN 1 ELSE 2 END LIMIT 1
    ) asset ON true
    LEFT JOIN LATERAL (
      SELECT array_agg(tag.name ORDER BY tag.name) AS tags
      FROM ai.image_tags image_tag JOIN ai.tags tag ON tag.id = image_tag.tag_id
      WHERE image_tag.image_id = i.id
    ) tag_list ON true`;
}

async function replaceTags(client: PoolClient, imageId: string, tags: readonly string[]): Promise<void> {
  await client.query("DELETE FROM ai.image_tags WHERE image_id = $1", [imageId]);
  for (const name of tags) {
    const slug = tagSlug(name);
    await client.query("INSERT INTO ai.tags (slug, name) VALUES ($1, $2) ON CONFLICT DO NOTHING", [slug, name]);
    const tag = await client.query<{ id: string }>("SELECT id FROM ai.tags WHERE slug = $1 OR name = $2 ORDER BY (slug = $1) DESC LIMIT 1", [slug, name]);
    if (tag.rows[0]) await client.query("INSERT INTO ai.image_tags (image_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", [imageId, tag.rows[0].id]);
  }
}

function tagSlug(name: string): string {
  const slug = name.toLowerCase().replace(/\s+/g, "-").replace(/[^\p{L}\p{N}_-]+/gu, "").slice(0, 80);
  return slug || "tag";
}
