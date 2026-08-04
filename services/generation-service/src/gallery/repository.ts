import type { DecodedCursor } from "./cursor.ts";
import type { AssetDeletionTask, DownloadGrant, GalleryFilters, GalleryImageDetail, GalleryImageSummary, InteractionResult, SeoImageEntry, ViewerContext } from "./types.ts";

export interface RepositoryPage<T> {
  readonly items: readonly T[];
  readonly next?: DecodedCursor;
}

export interface GalleryRepository {
  listPublic(filters: GalleryFilters, cursor: DecodedCursor | undefined, limit: number, viewer: ViewerContext): Promise<RepositoryPage<GalleryImageSummary>>;
  listOwned(userId: number, cursor: DecodedCursor | undefined, limit: number): Promise<RepositoryPage<GalleryImageSummary>>;
  listFavorites(userId: number, cursor: DecodedCursor | undefined, limit: number): Promise<RepositoryPage<GalleryImageSummary>>;
  findBySlug(slug: string, viewer: ViewerContext): Promise<GalleryImageDetail | undefined>;
  listSeoImages(cursor: DecodedCursor | undefined, limit: number): Promise<RepositoryPage<SeoImageEntry>>;
  setFavorite(imageId: string, userId: number, active: boolean, requestId: string): Promise<InteractionResult>;
  setLike(imageId: string, userId: number, active: boolean, requestId: string): Promise<InteractionResult>;
  softDelete(imageId: string, viewer: ViewerContext, retentionSeconds: number): Promise<{ readonly slug: string }>;
  createDownloadGrant(imageId: string, viewer: ViewerContext, ipHash?: string, userAgentHash?: string): Promise<DownloadGrant>;
  claimDeletionTasks(limit: number): Promise<readonly AssetDeletionTask[]>;
  completeDeletion(imageId: string): Promise<void>;
  failDeletion(imageId: string, safeError: string, retryAt: Date): Promise<void>;
}
