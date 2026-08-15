export type ViewerRole = "guest" | "user" | "admin";

export interface ViewerContext {
  readonly userId?: number;
  readonly role: ViewerRole;
  readonly requestId: string;
}

export interface GalleryFilters {
  readonly query?: string;
  readonly tag?: string;
  readonly workflow?: string;
  readonly orientation?: "portrait" | "square" | "landscape";
}

export interface GalleryPageRequest extends GalleryFilters {
  readonly cursor?: string;
  readonly limit?: number;
}

export interface ImageAssetView {
  readonly url: string;
  readonly width: number;
  readonly height: number;
  readonly mimeType: string;
  readonly variant: "original" | "preview" | "thumbnail";
}

export interface PublicCreatorView {
  readonly displayName: string;
  readonly avatarUrl?: string;
}

export interface GalleryImageSummary {
  readonly id: string;
  readonly slug: string;
  readonly title: string;
  readonly description: string;
  readonly width: number;
  readonly height: number;
  /** 作品媒体类型：视频与图片共用画廊、审核与发布链路。 */
  readonly mediaType: "image" | "video";
  /** 视频时长（秒），仅 mediaType=video 时返回。 */
  readonly durationSeconds?: number;
  readonly workflowName: string;
  readonly publishedAt: string;
  readonly asset: ImageAssetView;
  readonly creator?: PublicCreatorView;
  readonly tags: readonly string[];
  readonly likeCount: number;
  readonly favoriteCount: number;
  readonly viewerHasLiked: boolean;
  readonly viewerHasFavorited: boolean;
}

export interface GalleryImageDetail extends GalleryImageSummary {
  readonly prompt?: string;
  readonly negativePrompt?: string;
  readonly providerCode: string;
  readonly model?: string;
  readonly seed?: string;
  readonly sampler?: string;
  readonly cfg?: number;
  readonly steps?: number;
  readonly generationMs?: number;
  readonly createdAt: string;
  readonly downloadCount: number;
  readonly canDelete: boolean;
  readonly isOwner: boolean;
}

export interface GalleryPage<T> {
  readonly items: readonly T[];
  readonly nextCursor?: string;
}

export interface SeoImageEntry {
  readonly slug: string;
  readonly publishedAt: string;
  readonly assetUrl: string;
}

export interface InteractionResult {
  readonly active: boolean;
  readonly count: number;
}

export interface DownloadGrant {
  readonly url: string;
  readonly downloadCount: number;
}

export interface AssetDeletionTask {
  readonly imageId: string;
  readonly assets: readonly { readonly storageProvider: string; readonly objectKey: string }[];
  readonly attempt: number;
}
