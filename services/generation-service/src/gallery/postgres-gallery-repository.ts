import type { Pool, PoolClient, QueryResultRow } from "pg";
import type { GalleryAssetRecord, GalleryAssetUrlResolver } from "./asset-url.ts";
import type { DecodedCursor } from "./cursor.ts";
import { GalleryError } from "./errors.ts";
import type { GalleryRepository, RepositoryPage } from "./repository.ts";
import type { AssetDeletionTask, DownloadGrant, GalleryFilters, GalleryImageDetail, GalleryImageSummary, ImageAssetView, InteractionResult, SeoImageEntry, ViewerContext } from "./types.ts";

interface GalleryRow extends QueryResultRow {
  id: string;
  slug: string;
  title: string;
  description: string;
  prompt: string;
  negative_prompt: string;
  prompt_visibility: "public" | "hidden";
  visibility: "public" | "private";
  media_type: "image" | "video";
  duration_seconds: number | null;
  creator_user_id: number | null;
  provider_code_snapshot: string;
  model_snapshot: string | null;
  workflow_name_snapshot: string;
  seed: string | null;
  width: number;
  height: number;
  sampler: string | null;
  cfg: string | null;
  steps: number | null;
  generation_ms: number | null;
  like_count: number;
  favorite_count: number;
  download_count: number;
  published_at: Date | string | null;
  created_at: Date | string;
  display_name: string | null;
  avatar_url: string | null;
  tags: string[];
  viewer_has_liked: boolean;
  viewer_has_favorited: boolean;
  asset_variant: "original" | "preview" | "thumbnail";
  asset_storage_provider: string;
  asset_bucket: string;
  asset_region: string;
  asset_object_key: string;
  asset_public_url: string | null;
  asset_mime_type: string;
  asset_width: number;
  asset_height: number;
  page_at: Date | string;
}

interface SeoImageRow extends QueryResultRow {
  id: string;
  slug: string;
  published_at: Date | string;
  asset_storage_provider: string;
  asset_bucket: string;
  asset_region: string;
  asset_object_key: string;
  asset_public_url: string | null;
}

export class PostgresGalleryRepository implements GalleryRepository {
  readonly #pool: Pool;
  readonly #assets: GalleryAssetUrlResolver;

  constructor(pool: Pool, assets: GalleryAssetUrlResolver) {
    this.#pool = pool;
    this.#assets = assets;
  }

  async listPublic(filters: GalleryFilters, cursor: DecodedCursor | undefined, limit: number, viewer: ViewerContext): Promise<RepositoryPage<GalleryImageSummary>> {
    const values: unknown[] = [viewer.userId ?? null, limit + 1];
    const conditions = ["i.visibility = 'public'", "i.moderation_status = 'approved'", "i.deleted_at IS NULL", "i.published_at IS NOT NULL"];
    if (cursor) {
      values.push(cursor.at, cursor.id);
      conditions.push(`(i.published_at, i.id) < ($${values.length - 1}::timestamptz, $${values.length}::uuid)`);
    }
    if (filters.query) {
      values.push(`%${escapeLike(filters.query)}%`);
      conditions.push(`(i.title ILIKE $${values.length} ESCAPE '\\' OR i.description ILIKE $${values.length} ESCAPE '\\' OR (i.prompt_visibility = 'public' AND i.prompt ILIKE $${values.length} ESCAPE '\\'))`);
    }
    if (filters.tag) {
      values.push(filters.tag);
      conditions.push(`EXISTS (SELECT 1 FROM ai.image_tags fit JOIN ai.tags ft ON ft.id = fit.tag_id WHERE fit.image_id = i.id AND ft.slug = $${values.length})`);
    }
    if (filters.workflow) {
      values.push(filters.workflow);
      conditions.push(`i.workflow_name_snapshot = $${values.length}`);
    }
    if (filters.orientation === "portrait") conditions.push("i.height > i.width");
    if (filters.orientation === "square") conditions.push("i.height = i.width");
    if (filters.orientation === "landscape") conditions.push("i.width > i.height");
    const rows = await this.queryRows(`${baseSelect("list")}
      WHERE ${conditions.join(" AND ")}
      ORDER BY i.published_at DESC, i.id DESC
      LIMIT $2`, values);
    return this.toPage(rows, limit, "public");
  }

  async listOwned(userId: number, cursor: DecodedCursor | undefined, limit: number): Promise<RepositoryPage<GalleryImageSummary>> {
    const values: unknown[] = [userId, limit + 1];
    const conditions = ["i.creator_user_id = $1", "i.deleted_at IS NULL"];
    if (cursor) {
      values.push(cursor.at, cursor.id);
      conditions.push(`(i.created_at, i.id) < ($${values.length - 1}::timestamptz, $${values.length}::uuid)`);
    }
    const rows = await this.queryRows(`${baseSelect("owned")}
      WHERE ${conditions.join(" AND ")}
      ORDER BY i.created_at DESC, i.id DESC
      LIMIT $2`, values);
    return this.toPage(rows, limit, "owned");
  }

  async listFavorites(userId: number, cursor: DecodedCursor | undefined, limit: number): Promise<RepositoryPage<GalleryImageSummary>> {
    const values: unknown[] = [userId, limit + 1];
    const conditions = ["favorite.user_id = $1", "i.visibility = 'public'", "i.moderation_status = 'approved'", "i.deleted_at IS NULL"];
    if (cursor) {
      values.push(cursor.at, cursor.id);
      conditions.push(`(favorite.created_at, favorite.image_id) < ($${values.length - 1}::timestamptz, $${values.length}::uuid)`);
    }
    const rows = await this.queryRows(`${baseSelect("favorites")}
      JOIN ai.favorites favorite ON favorite.image_id = i.id
      WHERE ${conditions.join(" AND ")}
      ORDER BY favorite.created_at DESC, favorite.image_id DESC
      LIMIT $2`, values);
    return this.toPage(rows, limit, "favorites");
  }

  async findBySlug(slug: string, viewer: ViewerContext): Promise<GalleryImageDetail | undefined> {
    const result = await this.#pool.query<GalleryRow>(`${baseSelect("detail")}
      WHERE i.slug = $2
        AND i.deleted_at IS NULL
        AND (
          (i.visibility = 'public' AND i.moderation_status = 'approved')
          OR ($1::integer IS NOT NULL AND i.creator_user_id = $1)
          OR $3::boolean
        )
      LIMIT 1`, [viewer.userId ?? null, slug, viewer.role === "admin"]);
    const row = result.rows[0];
    if (!row) return undefined;
    return this.toDetail(row, viewer);
  }

  async listSeoImages(cursor: DecodedCursor | undefined, limit: number): Promise<RepositoryPage<SeoImageEntry>> {
    const values: unknown[] = [limit + 1];
    // og:image / sitemap 只接受图片资源；视频作品不进入 SEO 资产列表。
    const conditions = ["i.visibility = 'public'", "i.moderation_status = 'approved'", "i.deleted_at IS NULL", "i.published_at IS NOT NULL", "i.media_type = 'image'"];
    if (cursor) {
      values.push(cursor.at, cursor.id);
      conditions.push(`(i.published_at, i.id) < ($${values.length - 1}::timestamptz, $${values.length}::uuid)`);
    }
    const result = await this.#pool.query<SeoImageRow>(`SELECT i.id, i.slug, i.published_at,
        asset.storage_provider AS asset_storage_provider, asset.bucket AS asset_bucket,
        asset.region AS asset_region, asset.object_key AS asset_object_key,
        asset.public_url AS asset_public_url
      FROM ai.images i
      JOIN LATERAL (
        SELECT selected.* FROM ai.image_assets selected
        WHERE selected.image_id = i.id
        ORDER BY CASE selected.variant WHEN 'original' THEN 0 WHEN 'preview' THEN 1 ELSE 2 END
        LIMIT 1
      ) asset ON true
      WHERE ${conditions.join(" AND ")}
      ORDER BY i.published_at DESC, i.id DESC
      LIMIT $1`, values);
    const hasMore = result.rows.length > limit;
    const visible = result.rows.slice(0, limit);
    const items = await Promise.all(visible.map(async (row) => ({
      slug: row.slug,
      publishedAt: iso(row.published_at),
      assetUrl: await this.#assets.resolve({
        storageProvider: row.asset_storage_provider,
        bucket: row.asset_bucket,
        region: row.asset_region,
        objectKey: row.asset_object_key,
        ...(row.asset_public_url ? { publicUrl: row.asset_public_url } : {}),
      }, true),
    })));
    const last = hasMore ? visible.at(-1) : undefined;
    return { items, ...(last ? { next: { at: iso(last.published_at), id: last.id } } : {}) };
  }

  async setFavorite(imageId: string, userId: number, active: boolean, requestId: string): Promise<InteractionResult> {
    return this.setInteraction("favorites", "favorite_count", "favorite_changed", imageId, userId, active, requestId);
  }

  async setLike(imageId: string, userId: number, active: boolean, requestId: string): Promise<InteractionResult> {
    return this.setInteraction("likes", "like_count", "like_changed", imageId, userId, active, requestId);
  }

  async softDelete(imageId: string, viewer: ViewerContext, retentionSeconds: number): Promise<{ readonly slug: string }> {
    const userId = viewer.userId;
    if (!userId) throw new GalleryError("authentication_required", "Authentication is required", 401);
    return this.transaction(async (client) => {
      const result = await client.query<{ slug: string }>(`UPDATE ai.images
        SET deleted_at = now()
        WHERE id = $1 AND deleted_at IS NULL AND (creator_user_id = $2 OR $3::boolean)
        RETURNING slug`, [imageId, userId, viewer.role === "admin"]);
      const row = result.rows[0];
      if (!row) {
        const exists = await client.query<{ owner: boolean }>("SELECT creator_user_id = $2 AS owner FROM ai.images WHERE id = $1", [imageId, userId]);
        if (!exists.rows[0]) throw new GalleryError("image_not_found", "Image was not found", 404);
        throw new GalleryError("forbidden", "You cannot delete this image", 403);
      }
      await client.query(`INSERT INTO ai.asset_deletion_tasks (image_id, available_at)
        VALUES ($1, now() + ($2 * interval '1 second'))
        ON CONFLICT (image_id) DO UPDATE SET status = 'pending', available_at = EXCLUDED.available_at, last_error = NULL`, [imageId, retentionSeconds]);
      await insertAudit(client, viewer.requestId, userId, viewer.role, "gallery.image_deleted", imageId, { retentionSeconds });
      return row;
    });
  }

  async createDownloadGrant(imageId: string, viewer: ViewerContext, ipHash?: string, userAgentHash?: string): Promise<DownloadGrant> {
    return this.transaction(async (client) => {
      const result = await client.query<GalleryRow>(`${baseSelect("download")}
        WHERE i.id = $2 AND i.deleted_at IS NULL
          AND ((i.visibility = 'public' AND i.moderation_status = 'approved') OR ($1::integer IS NOT NULL AND i.creator_user_id = $1) OR $3::boolean)
        LIMIT 1`, [viewer.userId ?? null, imageId, viewer.role === "admin"]);
      const row = result.rows[0];
      if (!row) throw new GalleryError("image_not_found", "Image was not found", 404);
      await client.query("INSERT INTO ai.download_logs (image_id, user_id, ip_hash, user_agent_hash) VALUES ($1, $2, $3, $4)", [imageId, viewer.userId ?? null, ipHash ?? null, userAgentHash ?? null]);
      const countResult = await client.query<{ download_count: number }>("SELECT download_count FROM ai.images WHERE id = $1", [imageId]);
      const url = await this.#assets.resolve(assetRecord(row), row.visibility === "public");
      return { url, downloadCount: Number(countResult.rows[0]?.download_count ?? 0) };
    });
  }

  async claimDeletionTasks(limit: number): Promise<readonly AssetDeletionTask[]> {
    return this.transaction(async (client) => {
      const claimed = await client.query<{ image_id: string; attempts: number }>(`WITH due AS (
          SELECT image_id FROM ai.asset_deletion_tasks
          WHERE (status IN ('pending', 'failed') AND available_at <= now())
             OR (status = 'running' AND locked_at < now() - interval '15 minutes')
          ORDER BY available_at, image_id
          FOR UPDATE SKIP LOCKED
          LIMIT $1
        )
        UPDATE ai.asset_deletion_tasks task
        SET status = 'running', locked_at = now(), attempts = attempts + 1
        FROM due WHERE task.image_id = due.image_id
        RETURNING task.image_id, task.attempts`, [limit]);
      if (claimed.rows.length === 0) return [];
      const ids = claimed.rows.map((row) => row.image_id);
      const assets = await client.query<{ image_id: string; storage_provider: string; object_key: string }>("SELECT image_id, storage_provider, object_key FROM ai.image_assets WHERE image_id = ANY($1::uuid[]) ORDER BY image_id, object_key", [ids]);
      const byImage = new Map(ids.map((id) => [id, [] as Array<{ storageProvider: string; objectKey: string }>]));
      for (const asset of assets.rows) byImage.get(asset.image_id)?.push({ storageProvider: asset.storage_provider, objectKey: asset.object_key });
      const attempts = new Map(claimed.rows.map((row) => [row.image_id, row.attempts]));
      return ids.map((imageId) => ({ imageId, assets: byImage.get(imageId) ?? [], attempt: attempts.get(imageId) ?? 1 }));
    });
  }

  async completeDeletion(imageId: string): Promise<void> {
    await this.transaction(async (client) => {
      await client.query("DELETE FROM ai.image_assets WHERE image_id = $1", [imageId]);
      await client.query("UPDATE ai.asset_deletion_tasks SET status = 'completed', completed_at = now(), locked_at = NULL, last_error = NULL WHERE image_id = $1 AND status = 'running'", [imageId]);
    });
  }

  async failDeletion(imageId: string, safeError: string, retryAt: Date): Promise<void> {
    await this.#pool.query("UPDATE ai.asset_deletion_tasks SET status = 'failed', available_at = $2, locked_at = NULL, last_error = left($3, 500) WHERE image_id = $1 AND status = 'running'", [imageId, retryAt, safeError]);
  }

  private async setInteraction(table: "favorites" | "likes", countColumn: "favorite_count" | "like_count", action: string, imageId: string, userId: number, active: boolean, requestId: string): Promise<InteractionResult> {
    return this.transaction(async (client) => {
      const visible = await client.query("SELECT 1 FROM ai.images WHERE id = $1 AND visibility = 'public' AND moderation_status = 'approved' AND deleted_at IS NULL", [imageId]);
      if (visible.rowCount !== 1) throw new GalleryError("image_not_found", "Image was not found", 404);
      if (active) await client.query(`INSERT INTO ai.${table} (image_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING`, [imageId, userId]);
      else await client.query(`DELETE FROM ai.${table} WHERE image_id = $1 AND user_id = $2`, [imageId, userId]);
      const count = await client.query<Record<typeof countColumn, number>>(`SELECT ${countColumn} FROM ai.images WHERE id = $1`, [imageId]);
      await insertAudit(client, requestId, userId, "user", `gallery.${action}`, imageId, { active });
      return { active, count: Number(count.rows[0]?.[countColumn] ?? 0) };
    });
  }

  private async queryRows(sql: string, values: readonly unknown[]): Promise<readonly GalleryRow[]> {
    return (await this.#pool.query<GalleryRow>(sql, [...values])).rows;
  }

  private async toPage(rows: readonly GalleryRow[], limit: number, mode: "public" | "owned" | "favorites"): Promise<RepositoryPage<GalleryImageSummary>> {
    const hasMore = rows.length > limit;
    const visible = rows.slice(0, limit);
    const items = await Promise.all(visible.map((row) => this.toSummary(row)));
    const last = hasMore ? visible.at(-1) : undefined;
    return { items, ...(last ? { next: { at: iso(last.page_at), id: last.id } } : {}) };
  }

  private async toSummary(row: GalleryRow): Promise<GalleryImageSummary> {
    const asset = await this.toAsset(row);
    return {
      id: row.id,
      slug: row.slug,
      title: row.title,
      description: row.description,
      width: row.width,
      height: row.height,
      mediaType: row.media_type === "video" ? "video" : "image",
      ...(row.media_type === "video" && row.duration_seconds !== null ? { durationSeconds: Number(row.duration_seconds) } : {}),
      workflowName: row.workflow_name_snapshot,
      publishedAt: iso(row.published_at ?? row.created_at),
      asset,
      ...(row.display_name ? { creator: { displayName: row.display_name, ...(row.avatar_url ? { avatarUrl: row.avatar_url } : {}) } } : {}),
      tags: row.tags ?? [],
      likeCount: Number(row.like_count),
      favoriteCount: Number(row.favorite_count),
      viewerHasLiked: row.viewer_has_liked,
      viewerHasFavorited: row.viewer_has_favorited,
    };
  }

  private async toDetail(row: GalleryRow, viewer: ViewerContext): Promise<GalleryImageDetail> {
    const summary = await this.toSummary(row);
    const isOwner = !!viewer.userId && viewer.userId === row.creator_user_id;
    const maySeePrompt = row.prompt_visibility === "public" || isOwner || viewer.role === "admin";
    return {
      ...summary,
      ...(maySeePrompt ? { prompt: row.prompt, negativePrompt: row.negative_prompt } : {}),
      providerCode: row.provider_code_snapshot,
      ...(row.model_snapshot ? { model: row.model_snapshot } : {}),
      ...(row.seed !== null ? { seed: row.seed } : {}),
      ...(row.sampler ? { sampler: row.sampler } : {}),
      ...(row.cfg !== null ? { cfg: Number(row.cfg) } : {}),
      ...(row.steps !== null ? { steps: row.steps } : {}),
      ...(row.generation_ms !== null ? { generationMs: row.generation_ms } : {}),
      createdAt: iso(row.created_at),
      downloadCount: Number(row.download_count),
      canDelete: isOwner || viewer.role === "admin",
      isOwner,
    };
  }

  private async toAsset(row: GalleryRow): Promise<ImageAssetView> {
    return {
      url: await this.#assets.resolve(assetRecord(row), row.visibility === "public"),
      width: row.asset_width,
      height: row.asset_height,
      mimeType: row.asset_mime_type,
      variant: row.asset_variant,
    };
  }

  private async transaction<T>(work: (client: PoolClient) => Promise<T>): Promise<T> {
    const client = await this.#pool.connect();
    try {
      await client.query("BEGIN");
      const result = await work(client);
      await client.query("COMMIT");
      return result;
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }
}

function baseSelect(mode: "list" | "owned" | "favorites" | "detail" | "download"): string {
  const pageAt = mode === "favorites" ? "favorite.created_at" : mode === "owned" ? "i.created_at" : "COALESCE(i.published_at, i.created_at)";
  const variantOrder = mode === "detail" || mode === "download"
    ? "CASE selected.variant WHEN 'original' THEN 0 WHEN 'preview' THEN 1 ELSE 2 END"
    : "CASE selected.variant WHEN 'thumbnail' THEN 0 WHEN 'preview' THEN 1 ELSE 2 END";
  return `SELECT i.*, profile.display_name, profile.avatar_url,
      COALESCE(tag_list.tags, ARRAY[]::text[]) AS tags,
      ($1::integer IS NOT NULL AND EXISTS (SELECT 1 FROM ai.likes viewer_like WHERE viewer_like.image_id = i.id AND viewer_like.user_id = $1)) AS viewer_has_liked,
      ($1::integer IS NOT NULL AND EXISTS (SELECT 1 FROM ai.favorites viewer_favorite WHERE viewer_favorite.image_id = i.id AND viewer_favorite.user_id = $1)) AS viewer_has_favorited,
      asset.variant AS asset_variant, asset.storage_provider AS asset_storage_provider,
      asset.bucket AS asset_bucket, asset.region AS asset_region, asset.object_key AS asset_object_key,
      asset.public_url AS asset_public_url, asset.mime_type AS asset_mime_type,
      asset.width AS asset_width, asset.height AS asset_height,
      ${pageAt} AS page_at
    FROM ai.images i
    JOIN LATERAL (
      SELECT selected.* FROM ai.image_assets selected
      WHERE selected.image_id = i.id
      ORDER BY ${variantOrder}
      LIMIT 1
    ) asset ON true
    LEFT JOIN ai.user_profiles profile ON profile.user_id = i.creator_user_id
    LEFT JOIN LATERAL (
      SELECT array_agg(tag.name ORDER BY tag.name) AS tags
      FROM ai.image_tags image_tag JOIN ai.tags tag ON tag.id = image_tag.tag_id
      WHERE image_tag.image_id = i.id
    ) tag_list ON true`;
}

function assetRecord(row: GalleryRow): GalleryAssetRecord {
  return {
    storageProvider: row.asset_storage_provider,
    bucket: row.asset_bucket,
    region: row.asset_region,
    objectKey: row.asset_object_key,
    ...(row.asset_public_url ? { publicUrl: row.asset_public_url } : {}),
  };
}

async function insertAudit(client: PoolClient, requestId: string, userId: number, role: "guest" | "user" | "admin", action: string, imageId: string, metadata: Record<string, unknown>): Promise<void> {
  await client.query(`INSERT INTO ai.audit_logs (request_id, actor_user_id, actor_type, action, resource_type, resource_id, metadata)
    VALUES ($1::uuid, $2, $3, $4, 'image', $5, $6::jsonb)`, [requestId, userId, role === "admin" ? "admin" : "user", action, imageId, JSON.stringify(metadata)]);
}

function escapeLike(value: string): string {
  return value.replace(/[\\%_]/g, (match) => `\\${match}`);
}

function iso(value: Date | string): string {
  return (value instanceof Date ? value : new Date(value)).toISOString();
}
