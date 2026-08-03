/**
 * Gallery 前端共享类型。
 *
 * 与 Generation Service 的 `src/gallery/types.ts` 保持契约一致（前端只消费
 * 服务端返回的子集，并补充 BFF 请求参数 GalleryQuery / GalleryPageData）。
 * 浏览器不得接触 Provider 或存储凭证——本模块只描述传输层数据形状。
 */

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

/** BFF 请求参数：q 为搜索词，tag/workflow/orientation 为筛选，cursor/limit 为分页。 */
export interface GalleryQuery {
  readonly q?: string;
  readonly tag?: string;
  readonly workflow?: string;
  readonly orientation?: "portrait" | "square" | "landscape";
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

/** 画廊/我的图片/收藏列表的分页响应。 */
export interface GalleryPageData {
  readonly items: readonly GalleryImageSummary[];
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
