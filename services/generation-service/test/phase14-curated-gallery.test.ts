import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, it } from "node:test";
import sharp from "sharp";
import type { AdminCuratedImageItem, CreateCuratedImageCommand } from "../src/admin/types.ts";
import { GalleryError } from "../src/gallery/errors.ts";
import { CuratedImageService, type CuratedImageRepository } from "../src/gallery/curated-image-service.ts";
import type { StructuredLogger } from "../src/pipeline/structured-logger.ts";
import type { StorageProvider, StorageUpload, StoredAsset } from "../src/storage/storage-provider.ts";
import type { ViewerContext } from "../src/gallery/types.ts";

const ADMIN = 7;
const silentLogger: StructuredLogger = { info() {}, error() {} };

describe("Phase 14 curated gallery uploads", () => {
  it("rejects guests and non-admin viewers before touching storage", async () => {
    const storage = new FakeStorage();
    const service = curatedService(storage, new FakeCuratedRepository());
    await assert.rejects(service.create(input(), viewer("guest")), (error: unknown) => error instanceof GalleryError && error.statusCode === 401);
    await assert.rejects(service.create(input(), viewer("user", 9)), (error: unknown) => error instanceof GalleryError && error.statusCode === 403);
    assert.equal(storage.uploads.length, 0);
  });

  it("validates the payload and only accepts JPEG/PNG/WebP", async () => {
    const service = curatedService(new FakeStorage(), new FakeCuratedRepository());
    await assert.rejects(service.create({ ...input(), imageBase64: "not-base64!!" }, viewer("admin", ADMIN)), /base64/);
    await assert.rejects(service.create({ ...input(), prompt: "   " }, viewer("admin", ADMIN)), /prompt/);
    const svg = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"></svg>');
    await assert.rejects(service.create({ ...input(), imageBase64: svg.toString("base64") }, viewer("admin", ADMIN)), /JPEG/);
  });

  it("stores original, preview and thumbnail and keeps the prompt verbatim", async () => {
    const storage = new FakeStorage();
    const repository = new FakeCuratedRepository();
    const png = await sharp({ create: { width: 1200, height: 800, channels: 3, background: { r: 12, g: 34, b: 56 } } }).png().toBuffer();
    const prompt = "  第一行：柔和的逆光\n第二行：安静的室内，胶片质感\n--ar 3:2\n";
    const created = await curatedService(storage, repository).create({
      ...input(),
      imageBase64: `data:image/png;base64,${png.toString("base64")}`,
      prompt,
      title: "",
      tags: ["人像", " 人像 ", "Film"],
    }, viewer("admin", ADMIN));

    assert.equal(created.slug.startsWith("curated-"), true);
    assert.equal(repository.command?.prompt, prompt);
    assert.equal(repository.command?.title, "第一行：柔和的逆光");
    assert.deepEqual(repository.command?.tags, ["人像", "Film"]);
    assert.deepEqual(repository.command?.assets.map((asset) => asset.variant).sort(), ["original", "preview", "thumbnail"]);
    const preview = repository.command?.assets.find((asset) => asset.variant === "preview");
    assert.equal(preview?.width, 1200);
    assert.equal(preview?.height, 800);
    const thumbnail = repository.command?.assets.find((asset) => asset.variant === "thumbnail");
    assert.equal(thumbnail?.width, 720);
    assert.equal(thumbnail?.mimeType, "image/webp");
    assert.equal(repository.command?.promptVisibility, "public");
    assert.equal(storage.uploads.length, 3);
    assert.equal(storage.uploads.every((upload) => upload.objectKey.startsWith("curated/")), true);
  });

  it("cleans up uploaded objects when the database write fails", async () => {
    const storage = new FakeStorage();
    const repository = new FakeCuratedRepository();
    repository.failCreate = true;
    const png = await sharp({ create: { width: 64, height: 64, channels: 3, background: { r: 1, g: 2, b: 3 } } }).png().toBuffer();
    await assert.rejects(
      curatedService(storage, repository).create({ ...input(), imageBase64: png.toString("base64") }, viewer("admin", ADMIN)),
      (error: unknown) => error instanceof GalleryError && error.code === "service_unavailable",
    );
    assert.deepEqual(storage.deleted.sort(), storage.uploads.map((upload) => upload.objectKey).sort());
  });

  it("keeps committed assets when cache invalidation fails", async () => {
    const storage = new FakeStorage();
    const repository = new FakeCuratedRepository();
    const png = await sharp({ create: { width: 64, height: 64, channels: 3, background: { r: 1, g: 2, b: 3 } } }).png().toBuffer();
    const service = new CuratedImageService({
      storage, repository, logger: silentLogger,
      onMutated: async () => { throw new Error("cache unavailable"); },
      retentionSeconds: 86_400,
    });
    const created = await service.create({ ...input(), imageBase64: png.toString("base64") }, viewer("admin", ADMIN));
    assert.equal(created.slug, repository.command?.slug);
    assert.equal(storage.uploads.length, 3);
    assert.deepEqual(storage.deleted, []);
  });

  it("requires the configured curated service and validates list limits", async () => {
    const service = curatedService(new FakeStorage(), new FakeCuratedRepository());
    await assert.rejects(service.list(viewer("admin", ADMIN), 0), /limit/);
    await assert.rejects(service.list(viewer("user", 9)), (error: unknown) => error instanceof GalleryError && error.statusCode === 403);
    assert.equal((await service.list(viewer("admin", ADMIN))).length, 1);
  });
});

class FakeStorage implements StorageProvider {
  readonly code = "fake";
  readonly uploads: { objectKey: string; contentType: string }[] = [];
  readonly deleted: string[] = [];
  async upload(input: StorageUpload): Promise<StoredAsset> {
    this.uploads.push({ objectKey: input.objectKey, contentType: input.contentType });
    return { storageProvider: this.code, bucket: "bucket", region: "ap-test", objectKey: input.objectKey, url: `https://cdn.example.test/${input.objectKey}` };
  }
  async download(): Promise<Buffer> { return Buffer.alloc(0); }
  async delete(objectKey: string): Promise<void> { this.deleted.push(objectKey); }
}

class FakeCuratedRepository implements CuratedImageRepository {
  command: CreateCuratedImageCommand | undefined;
  failCreate = false;
  async createCuratedImage(command: CreateCuratedImageCommand): Promise<AdminCuratedImageItem> {
    if (this.failCreate) throw new Error("database is unavailable");
    this.command = command;
    return itemOf(command);
  }
  async updateCuratedImage(): Promise<AdminCuratedImageItem> { return itemOf(this.command); }
  async listCuratedImages(): Promise<readonly AdminCuratedImageItem[]> { return [itemOf(this.command)]; }
  async deleteCuratedImage(): Promise<{ slug: string }> { return { slug: "curated-one" }; }
}

function curatedService(storage: StorageProvider, repository: CuratedImageRepository): CuratedImageService {
  return new CuratedImageService({ storage, repository, logger: silentLogger, onMutated: async () => {}, retentionSeconds: 86_400 });
}

function itemOf(command: CreateCuratedImageCommand | undefined): AdminCuratedImageItem {
  return {
    id: "123e4567-e89b-42d3-a456-426614174000",
    slug: command?.slug ?? "curated-one",
    title: command?.title ?? "Curated",
    description: command?.description ?? "",
    prompt: command?.prompt ?? "",
    negativePrompt: command?.negativePrompt ?? "",
    model: command?.model ?? "gpt-image-1",
    tags: command?.tags ?? [],
    width: command?.width ?? 1024,
    height: command?.height ?? 1024,
    mediaType: "image",
    promptVisibility: command?.promptVisibility ?? "public",
    thumbnailUrl: "https://cdn.example.test/thumbnail.webp",
    createdAt: "2026-10-24T00:00:00.000Z",
    updatedAt: "2026-10-24T00:00:00.000Z",
  };
}

function input(): Record<string, unknown> {
  return {
    imageBase64: Buffer.from("placeholder").toString("base64"),
    prompt: "a quiet portrait",
    model: "gpt-image-1",
  };
}

function viewer(role: "guest" | "user" | "admin", userId?: number): ViewerContext {
  return { role, requestId: randomUUID(), ...(userId ? { userId } : {}) };
}
