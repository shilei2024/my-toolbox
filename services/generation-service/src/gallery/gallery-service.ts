import { createHash } from "node:crypto";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import type { GalleryCache } from "./cache.ts";
import type { GalleryCursorCodec } from "./cursor.ts";
import { GalleryError } from "./errors.ts";
import type { GalleryRepository } from "./repository.ts";
import type { DownloadGrant, GalleryFacets, GalleryFilters, GalleryImageDetail, GalleryImageSummary, GalleryPage, GalleryPageRequest, InteractionResult, SeoImageEntry, ViewerContext } from "./types.ts";

const PUBLIC_FEED_NAMESPACE = "gallery:public-feed";

export class GalleryService {
  readonly #repository: GalleryRepository;
  readonly #cursor: GalleryCursorCodec;
  readonly #cache: GalleryCache;
  readonly #logger: StructuredLogger;
  readonly #cacheTtlSeconds: number;
  readonly #deletionRetentionSeconds: number;

  constructor(options: {
    repository: GalleryRepository;
    cursor: GalleryCursorCodec;
    cache: GalleryCache;
    logger: StructuredLogger;
    cacheTtlSeconds: number;
    deletionRetentionSeconds: number;
  }) {
    this.#repository = options.repository;
    this.#cursor = options.cursor;
    this.#cache = options.cache;
    this.#logger = options.logger;
    this.#cacheTtlSeconds = options.cacheTtlSeconds;
    this.#deletionRetentionSeconds = options.deletionRetentionSeconds;
  }

  async listPublic(request: GalleryPageRequest, viewer: ViewerContext): Promise<GalleryPage<GalleryImageSummary>> {
    const limit = normalizedLimit(request.limit);
    const filters = normalizedFilters(request);
    const sort = request.sort === "popular" ? "popular" : "latest";
    // "热门"按收藏数排序，与 keyset（published_at, id）不一致：只返回第一屏，
    // 不签发 cursor，避免跨页重复或漏项。
    const scope = publicScope(filters);
    const cursor = sort === "popular" ? undefined : this.#cursor.decode(scope, request.cursor);
    const cacheable = viewer.role === "guest";
    const version = cacheable ? await this.#cache.version(PUBLIC_FEED_NAMESPACE) : "private";
    const key = `gallery:list:${version}:${hashKey({ filters, cursor, limit, sort })}`;
    if (cacheable) {
      const cached = await this.#cache.get<GalleryPage<GalleryImageSummary>>(key);
      if (cached) return cached;
    }
    const result = await this.#repository.listPublic(filters, cursor, limit, viewer, sort);
    const page = toPage(result.items, result.next && sort === "latest" ? this.#cursor.encode(scope, result.next) : undefined);
    if (cacheable) await this.#cache.set(key, page, this.#cacheTtlSeconds);
    return page;
  }

  /** 筛选面板的聚合数据（模型分布、图片/视频构成）。 */
  async facets(): Promise<GalleryFacets> {
    const version = await this.#cache.version(PUBLIC_FEED_NAMESPACE);
    const key = `gallery:facets:${version}`;
    const cached = await this.#cache.get<GalleryFacets>(key);
    if (cached) return cached;
    const result = await this.#repository.facets();
    await this.#cache.set(key, result, this.#cacheTtlSeconds);
    return result;
  }

  async listMine(request: GalleryPageRequest, viewer: ViewerContext): Promise<GalleryPage<GalleryImageSummary>> {
    const userId = requireUser(viewer);
    const scope = `mine:${userId}`;
    const result = await this.#repository.listOwned(userId, this.#cursor.decode(scope, request.cursor), normalizedLimit(request.limit));
    return toPage(result.items, result.next ? this.#cursor.encode(scope, result.next) : undefined);
  }

  async listFavorites(request: GalleryPageRequest, viewer: ViewerContext): Promise<GalleryPage<GalleryImageSummary>> {
    const userId = requireUser(viewer);
    const scope = `favorites:${userId}`;
    const result = await this.#repository.listFavorites(userId, this.#cursor.decode(scope, request.cursor), normalizedLimit(request.limit));
    return toPage(result.items, result.next ? this.#cursor.encode(scope, result.next) : undefined);
  }

  async getBySlug(slug: string, viewer: ViewerContext): Promise<GalleryImageDetail> {
    const normalizedSlug = normalizeSlug(slug);
    const cacheKey = detailCacheKey(normalizedSlug);
    if (viewer.role === "guest") {
      const cached = await this.#cache.get<GalleryImageDetail>(cacheKey);
      if (cached) return cached;
    }
    const image = await this.#repository.findBySlug(normalizedSlug, viewer);
    if (!image) throw new GalleryError("image_not_found", "Image was not found", 404);
    if (viewer.role === "guest") {
      await Promise.all([
        this.#cache.set(cacheKey, image, this.#cacheTtlSeconds),
        this.#cache.set(detailIdCacheKey(image.id), normalizedSlug, this.#cacheTtlSeconds),
      ]);
    }
    return image;
  }

  async listSeoImages(request: Pick<GalleryPageRequest, "cursor" | "limit">): Promise<GalleryPage<SeoImageEntry>> {
    const limit = normalizedSeoLimit(request.limit);
    const scope = "seo:public";
    const result = await this.#repository.listSeoImages(this.#cursor.decode(scope, request.cursor), limit);
    return toPage(result.items, result.next ? this.#cursor.encode(scope, result.next) : undefined);
  }

  async setFavorite(imageId: string, active: boolean, viewer: ViewerContext): Promise<InteractionResult> {
    const userId = requireUser(viewer);
    const result = await this.#repository.setFavorite(normalizeImageId(imageId), userId, active, viewer.requestId);
    await this.invalidateMutatedImage(normalizeImageId(imageId));
    this.#logger.info("gallery.favorite_changed", { requestId: viewer.requestId, imageId, actorUserId: userId, active: result.active });
    return result;
  }

  async setLike(imageId: string, active: boolean, viewer: ViewerContext): Promise<InteractionResult> {
    const userId = requireUser(viewer);
    const result = await this.#repository.setLike(normalizeImageId(imageId), userId, active, viewer.requestId);
    await this.invalidateMutatedImage(normalizeImageId(imageId));
    this.#logger.info("gallery.like_changed", { requestId: viewer.requestId, imageId, actorUserId: userId, active: result.active });
    return result;
  }

  async deleteImage(imageId: string, viewer: ViewerContext): Promise<void> {
    requireUser(viewer);
    const normalizedId = normalizeImageId(imageId);
    const result = await this.#repository.softDelete(normalizedId, viewer, this.#deletionRetentionSeconds);
    await Promise.all([this.#cache.delete(detailCacheKey(result.slug)), this.#cache.bump(PUBLIC_FEED_NAMESPACE)]);
    this.#logger.info("gallery.image_soft_deleted", { requestId: viewer.requestId, imageId: normalizedId, actorUserId: viewer.userId ?? 0, actorRole: viewer.role });
  }

  async grantDownload(imageId: string, viewer: ViewerContext, ip?: string, userAgent?: string): Promise<DownloadGrant> {
    const normalizedId = normalizeImageId(imageId);
    const result = await this.#repository.createDownloadGrant(normalizedId, viewer, sha256(ip), sha256(userAgent));
    await this.invalidateMutatedImage(normalizedId);
    return result;
  }

  async invalidatePublicData(): Promise<void> {
    await this.#cache.bump(PUBLIC_FEED_NAMESPACE);
  }

  /** 管理员改动策展作品后，按 slug 清理详情缓存并刷新公共列表版本。 */
  async invalidateImageDetail(slug: string): Promise<void> {
    await Promise.all([this.#cache.delete(detailCacheKey(slug)), this.#cache.bump(PUBLIC_FEED_NAMESPACE)]);
  }

  private async invalidateMutatedImage(imageId: string): Promise<void> {
    const idKey = detailIdCacheKey(imageId);
    const slug = await this.#cache.get<string>(idKey);
    await Promise.all([this.#cache.delete(idKey), ...(slug ? [this.#cache.delete(detailCacheKey(slug))] : [])]);
  }
}

function normalizedLimit(limit?: number): number {
  if (limit === undefined) return 24;
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) throw new GalleryError("invalid_request", "limit must be an integer between 1 and 50", 400);
  return limit;
}

function normalizedSeoLimit(limit?: number): number {
  if (limit === undefined) return 500;
  if (!Number.isInteger(limit) || limit < 1 || limit > 5_000) throw new GalleryError("invalid_request", "limit must be an integer between 1 and 5000", 400);
  return limit;
}

function normalizedFilters(request: GalleryPageRequest): GalleryFilters {
  return {
    ...(request.query ? { query: normalizeText(request.query, 120, "query") } : {}),
    ...(request.tag ? { tag: normalizeToken(request.tag, 80, "tag") } : {}),
    ...(request.workflow ? { workflow: normalizeText(request.workflow, 128, "workflow") } : {}),
    ...(request.orientation ? { orientation: request.orientation } : {}),
    ...(request.mediaType ? { mediaType: request.mediaType } : {}),
  };
}

function normalizeSlug(value: string): string {
  const slug = value.trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9-]{0,254}$/.test(slug)) throw new GalleryError("invalid_request", "Image slug is invalid", 400);
  return slug;
}

function normalizeImageId(value: string): string {
  const id = value.trim().toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f-]{27}$/.test(id)) throw new GalleryError("invalid_request", "Image id is invalid", 400);
  return id;
}

function normalizeText(value: string, max: number, field: string): string {
  const normalized = value.trim().replace(/\s+/g, " ");
  if (!normalized || normalized.length > max) throw new GalleryError("invalid_request", `${field} is invalid`, 400);
  return normalized;
}

function normalizeToken(value: string, max: number, field: string): string {
  const normalized = value.trim().toLowerCase();
  if (!new RegExp(`^[a-z0-9\\p{L}][a-z0-9\\p{L}_-]{0,${max - 1}}$`, "u").test(normalized)) throw new GalleryError("invalid_request", `${field} is invalid`, 400);
  return normalized;
}

function requireUser(viewer: ViewerContext): number {
  if (viewer.role === "guest" || !Number.isInteger(viewer.userId) || (viewer.userId ?? 0) <= 0) throw new GalleryError("authentication_required", "Authentication is required", 401);
  return viewer.userId as number;
}

function publicScope(filters: GalleryFilters): string {
  // Cursor scopes accept lowercase ASCII only; base64url hashes may contain
  // uppercase letters and reject every page that needs a next cursor.
  return `public:${createHash("sha256").update(JSON.stringify(filters)).digest("hex").slice(0, 20)}`;
}

function hashKey(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("base64url");
}

function sha256(value?: string): string | undefined {
  return value ? createHash("sha256").update(value).digest("hex") : undefined;
}

function detailCacheKey(slug: string): string { return `gallery:detail:${slug}`; }
function detailIdCacheKey(imageId: string): string { return `gallery:detail-id:${imageId}`; }

function toPage<T>(items: readonly T[], nextCursor?: string): GalleryPage<T> {
  return { items, ...(nextCursor ? { nextCursor } : {}) };
}
