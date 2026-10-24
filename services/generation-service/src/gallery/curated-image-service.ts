import { createHash, randomBytes } from "node:crypto";
import sharp from "sharp";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import type { StorageProvider } from "../storage/storage-provider.ts";
import type { AdminCuratedImageItem, CreateCuratedImageCommand, CuratedImageAssetRecord, UpdateCuratedImageCommand } from "../admin/types.ts";
import { GalleryError } from "./errors.ts";
import type { ViewerContext } from "./types.ts";

/** 管理员把图片 + 提示词直接发布到画廊的写入口。 */
export interface CuratedImageRepository {
  createCuratedImage(command: CreateCuratedImageCommand, adminUserId: number, requestId: string): Promise<AdminCuratedImageItem>;
  updateCuratedImage(imageId: string, command: UpdateCuratedImageCommand, adminUserId: number, requestId: string): Promise<AdminCuratedImageItem>;
  listCuratedImages(limit: number): Promise<readonly AdminCuratedImageItem[]>;
  deleteCuratedImage(imageId: string, adminUserId: number, requestId: string, retentionSeconds: number): Promise<{ readonly slug: string }>;
}

const MAX_IMAGE_BYTES = 15 * 1024 * 1024;
const MAX_TITLE = 180;
const MAX_PROMPT = 8000;
const MAX_NEGATIVE_PROMPT = 4000;
const MAX_DESCRIPTION = 2000;
const MAX_MODEL = 128;
const MAX_TAGS = 8;
const MAX_TAG_LENGTH = 40;
const PREVIEW_EDGE = 1600;
const THUMBNAIL_EDGE = 720;
const ALLOWED_FORMATS = new Set(["jpeg", "png", "webp"]);

export class CuratedImageService {
  readonly #storage: StorageProvider;
  readonly #repository: CuratedImageRepository;
  readonly #logger: StructuredLogger;
  readonly #onMutated: (slug: string) => Promise<void>;
  readonly #retentionSeconds: number;

  constructor(options: {
    storage: StorageProvider;
    repository: CuratedImageRepository;
    logger: StructuredLogger;
    /** 作品内容变化后清理画廊缓存（详情 + 公共列表）。 */
    onMutated: (slug: string) => Promise<void>;
    retentionSeconds: number;
  }) {
    this.#storage = options.storage;
    this.#repository = options.repository;
    this.#logger = options.logger;
    this.#onMutated = options.onMutated;
    this.#retentionSeconds = options.retentionSeconds;
  }

  async create(input: unknown, viewer: ViewerContext): Promise<AdminCuratedImageItem> {
    const adminUserId = requireAdmin(viewer);
    const command = parseCreate(input);
    const slug = `curated-${Date.now().toString(36)}-${randomBytes(4).toString("hex")}`;
    const assets: CuratedImageAssetRecord[] = [];
    let committed = false;
    try {
      const rendered = await renderAssets(command.image, slug);
      for (const item of rendered) {
        const stored = await this.#storage.upload({ objectKey: item.objectKey, body: item.body, contentType: item.mimeType, contentLength: item.body.byteLength });
        assets.push({
          variant: item.variant,
          storageProvider: stored.storageProvider,
          bucket: stored.bucket,
          region: stored.region,
          objectKey: stored.objectKey,
          ...(stored.url ? { publicUrl: stored.url } : {}),
          mimeType: item.mimeType,
          byteSize: item.body.byteLength,
          width: item.width,
          height: item.height,
          sha256: item.sha256,
        });
      }
      const created = await this.#repository.createCuratedImage({
        slug,
        title: command.title,
        description: command.description,
        prompt: command.prompt,
        negativePrompt: command.negativePrompt,
        model: command.model,
        tags: command.tags,
        width: rendered[0]?.width ?? 0,
        height: rendered[0]?.height ?? 0,
        promptVisibility: command.promptVisibility,
        assets,
      }, adminUserId, viewer.requestId);
      // A committed image must keep its objects even when cache invalidation fails.
      committed = true;
      try {
        await this.#onMutated(created.slug);
      } catch {
        this.#logger.error("admin.curated_image_cache_invalidation_failed", { requestId: viewer.requestId, imageId: created.id });
      }
      this.#logger.info("admin.curated_image_created", { requestId: viewer.requestId, actorUserId: adminUserId, imageId: created.id, slug: created.slug, model: created.model });
      return created;
    } catch (error) {
      // 数据库写入失败时回收已上传对象，避免产生无主文件。
      if (!committed) await Promise.allSettled(assets.map((asset) => this.#storage.delete(asset.objectKey)));
      throw normalizeStorageError(error);
    }
  }

  async update(imageId: string, input: unknown, viewer: ViewerContext): Promise<AdminCuratedImageItem> {
    const adminUserId = requireAdmin(viewer);
    const command = parseUpdate(input);
    const updated = await this.#repository.updateCuratedImage(normalizeImageId(imageId), command, adminUserId, viewer.requestId);
    await this.#onMutated(updated.slug);
    this.#logger.info("admin.curated_image_updated", { requestId: viewer.requestId, actorUserId: adminUserId, imageId: updated.id });
    return updated;
  }

  async list(viewer: ViewerContext, limit?: number): Promise<readonly AdminCuratedImageItem[]> {
    requireAdmin(viewer);
    const normalized = limit === undefined ? 30 : limit;
    if (!Number.isInteger(normalized) || normalized < 1 || normalized > 100) throw invalid("limit must be between 1 and 100");
    return this.#repository.listCuratedImages(normalized);
  }

  async delete(imageId: string, viewer: ViewerContext): Promise<void> {
    const adminUserId = requireAdmin(viewer);
    const id = normalizeImageId(imageId);
    const result = await this.#repository.deleteCuratedImage(id, adminUserId, viewer.requestId, this.#retentionSeconds);
    await this.#onMutated(result.slug);
    this.#logger.info("admin.curated_image_deleted", { requestId: viewer.requestId, actorUserId: adminUserId, imageId: id, slug: result.slug });
  }
}

interface ParsedCreate {
  readonly image: Buffer;
  readonly title: string;
  readonly description: string;
  readonly prompt: string;
  readonly negativePrompt: string;
  readonly model: string;
  readonly tags: readonly string[];
  readonly promptVisibility: "public" | "hidden";
}

function parseCreate(value: unknown): ParsedCreate {
  const body = object(value, ["imageBase64", "title", "description", "prompt", "negativePrompt", "model", "tags", "promptVisibility"]);
  const image = decodeImage(body.imageBase64);
    const prompt = requiredPrompt(body.prompt, MAX_PROMPT, "prompt");
  const model = requiredText(body.model, MAX_MODEL, "model");
  const title = optionalText(body.title, MAX_TITLE) || fallbackTitle(prompt);
  return {
    image,
    title,
    description: optionalText(body.description, MAX_DESCRIPTION),
    prompt,
    negativePrompt: optionalPrompt(body.negativePrompt, MAX_NEGATIVE_PROMPT),
    model,
    tags: normalizeTags(body.tags),
    promptVisibility: body.promptVisibility === "hidden" ? "hidden" : "public",
  };
}

function parseUpdate(value: unknown): UpdateCuratedImageCommand {
  const body = object(value, ["title", "description", "prompt", "negativePrompt", "model", "tags", "promptVisibility"]);
  const command: {
    title?: string;
    description?: string;
    prompt?: string;
    negativePrompt?: string;
    model?: string;
    tags?: readonly string[];
    promptVisibility?: "public" | "hidden";
  } = {};
  if (body.title !== undefined) command.title = requiredText(body.title, MAX_TITLE, "title");
  if (body.description !== undefined) command.description = optionalText(body.description, MAX_DESCRIPTION);
  if (body.prompt !== undefined) command.prompt = requiredPrompt(body.prompt, MAX_PROMPT, "prompt");
  if (body.negativePrompt !== undefined) command.negativePrompt = optionalPrompt(body.negativePrompt, MAX_NEGATIVE_PROMPT);
  if (body.model !== undefined) command.model = requiredText(body.model, MAX_MODEL, "model");
  if (body.tags !== undefined) command.tags = normalizeTags(body.tags);
  if (body.promptVisibility === "public" || body.promptVisibility === "hidden") command.promptVisibility = body.promptVisibility;
  if (Object.keys(command).length === 0) throw invalid("Nothing to update");
  return command;
}

interface RenderItem {
  readonly variant: CuratedImageAssetRecord["variant"];
  readonly objectKey: string;
  readonly mimeType: string;
  readonly body: Buffer;
  readonly width: number;
  readonly height: number;
  readonly sha256: string;
}

async function renderAssets(image: Buffer, slug: string): Promise<readonly RenderItem[]> {
  const probe = await sharp(image, { failOn: "error", limitInputPixels: 100_000_000 }).metadata().catch(() => undefined);
  if (!probe?.format || !ALLOWED_FORMATS.has(probe.format)) throw invalid("仅支持 JPEG / PNG / WebP 图片");
  const format = probe.format === "jpeg" ? "jpeg" : probe.format === "png" ? "png" : "webp";
  const extension = format === "jpeg" ? "jpg" : format;
  const prefix = `curated/${new Date().toISOString().slice(0, 7).replace("-", "/")}/${slug}`;
  // rotate() 按 EXIF 方向摆正并丢弃元数据，避免公开图带出拍摄/软件信息。
  const originalPipeline = sharp(image).rotate();
  const original = await (format === "jpeg" ? originalPipeline.jpeg({ quality: 92, mozjpeg: true }) : format === "png" ? originalPipeline.png({ compressionLevel: 9 }) : originalPipeline.webp({ quality: 92 }))
    .toBuffer({ resolveWithObject: true });
  const preview = await sharp(image).rotate().resize({ width: PREVIEW_EDGE, height: PREVIEW_EDGE, fit: "inside", withoutEnlargement: true }).webp({ quality: 82 }).toBuffer({ resolveWithObject: true });
  const thumbnail = await sharp(image).rotate().resize({ width: THUMBNAIL_EDGE, height: THUMBNAIL_EDGE, fit: "inside", withoutEnlargement: true }).webp({ quality: 80 }).toBuffer({ resolveWithObject: true });
  return [
    { variant: "original", objectKey: `${prefix}/original.${extension}`, mimeType: `image/${format}`, body: original.data, width: original.info.width, height: original.info.height, sha256: digest(original.data) },
    { variant: "preview", objectKey: `${prefix}/preview.webp`, mimeType: "image/webp", body: preview.data, width: preview.info.width, height: preview.info.height, sha256: digest(preview.data) },
    { variant: "thumbnail", objectKey: `${prefix}/thumbnail.webp`, mimeType: "image/webp", body: thumbnail.data, width: thumbnail.info.width, height: thumbnail.info.height, sha256: digest(thumbnail.data) },
  ];
}

function decodeImage(value: unknown): Buffer {
  if (typeof value !== "string" || value.trim() === "") throw invalid("imageBase64 is required");
  const raw = value.startsWith("data:") ? value.slice(value.indexOf(",") + 1) : value;
  const normalized = raw.replace(/\s+/g, "");
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(normalized)) throw invalid("imageBase64 is not valid base64");
  const buffer = Buffer.from(normalized, "base64");
  if (buffer.byteLength === 0) throw invalid("imageBase64 is empty");
  if (buffer.byteLength > MAX_IMAGE_BYTES) throw new GalleryError("invalid_request", `图片超过 ${Math.floor(MAX_IMAGE_BYTES / 1024 / 1024)}MB 上限`, 413);
  return buffer;
}

function normalizeTags(value: unknown): readonly string[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw invalid("tags must be an array");
  const seen = new Set<string>();
  const tags: string[] = [];
  for (const item of value) {
    if (typeof item !== "string") throw invalid("tags must be strings");
    const tag = item.trim().replace(/\s+/g, " ");
    if (!tag) continue;
    if (tag.length > MAX_TAG_LENGTH) throw invalid(`单个标签最多 ${MAX_TAG_LENGTH} 个字符`);
    const key = tag.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    tags.push(tag);
  }
  if (tags.length > MAX_TAGS) throw invalid(`标签最多 ${MAX_TAGS} 个`);
  return tags;
}

function fallbackTitle(prompt: string): string {
  const firstLine = prompt.split(/\r?\n/, 1)[0]?.trim() ?? "";
  return (firstLine || "未命名作品").slice(0, 40);
}

function requiredText(value: unknown, max: number, field: string): string {
  if (typeof value !== "string") throw invalid(`${field} is required`);
  const text = value.trim();
  if (!text) throw invalid(`${field} is required`);
  if (text.length > max) throw invalid(`${field} must be at most ${max} characters`);
  return text;
}

function requiredPrompt(value: unknown, max: number, field: string): string {
  if (typeof value !== "string" || !value.trim()) throw invalid(`${field} is required`);
  if (value.length > max) throw invalid(`${field} must be at most ${max} characters`);
  return value;
}

function optionalText(value: unknown, max: number): string {
  if (value === undefined || value === null) return "";
  if (typeof value !== "string") throw invalid("text field must be a string");
  const text = value.trim();
  if (text.length > max) throw invalid(`text field must be at most ${max} characters`);
  return text;
}

function optionalPrompt(value: unknown, max: number): string {
  if (value === undefined || value === null) return "";
  if (typeof value !== "string") throw invalid("text field must be a string");
  if (value.length > max) throw invalid(`text field must be at most ${max} characters`);
  return value;
}

function object(value: unknown, allowed: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid("request body is invalid");
  const result = value as Record<string, unknown>;
  if (Object.keys(result).some((key) => !allowed.includes(key))) throw invalid("request body contains unsupported fields");
  return result;
}

function requireAdmin(viewer: ViewerContext): number {
  if (viewer.role === "guest") throw new GalleryError("authentication_required", "Authentication is required", 401);
  if (viewer.role !== "admin" || !Number.isInteger(viewer.userId) || (viewer.userId ?? 0) <= 0) throw new GalleryError("forbidden", "Administrator permission is required", 403);
  return viewer.userId as number;
}

function normalizeImageId(value: string): string {
  const id = value.trim().toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f-]{27}$/.test(id)) throw invalid("image id is invalid");
  return id;
}

function digest(buffer: Buffer): string { return createHash("sha256").update(buffer).digest("hex"); }
function invalid(message: string): GalleryError { return new GalleryError("invalid_request", message, 400); }

function normalizeStorageError(error: unknown): unknown {
  if (error instanceof GalleryError) return error;
  // 存储/图片处理的内部错误不下发到浏览器，由上层日志排查。
  return new GalleryError("service_unavailable", "策展图片保存失败，请稍后重试", 503);
}
