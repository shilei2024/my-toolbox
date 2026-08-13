import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, it } from "node:test";
import type { StructuredLogger } from "../src/pipeline/structured-logger.ts";
import type { StorageProvider } from "../src/storage/storage-provider.ts";
import { GalleryAssetDeletionWorker } from "../src/gallery/asset-deletion-worker.ts";
import { TencentCosGalleryAssetUrlResolver } from "../src/gallery/asset-url.ts";
import type { GalleryCache } from "../src/gallery/cache.ts";
import { loadGalleryConfig } from "../src/gallery/config.ts";
import { GalleryCursorCodec } from "../src/gallery/cursor.ts";
import { GalleryError } from "../src/gallery/errors.ts";
import { GalleryService } from "../src/gallery/gallery-service.ts";
import { createGalleryHttpServer } from "../src/gallery/http-server.ts";
import { InternalViewerContextCodec, USER_CONTEXT_HEADER, USER_CONTEXT_SIGNATURE_HEADER } from "../src/gallery/internal-auth.ts";
import type { GalleryRepository } from "../src/gallery/repository.ts";
import type { AssetDeletionTask, GalleryImageDetail, GalleryImageSummary, ViewerContext } from "../src/gallery/types.ts";

const SECRET = "phase-six-test-secret-that-is-long-enough-123456";
const IMAGE_ID = "123e4567-e89b-42d3-a456-426614174000";
const REQUEST_ID = "223e4567-e89b-42d3-a456-426614174000";

describe("Phase 6 Gallery cursor and internal identity", () => {
  it("signs scoped keyset cursors and rejects tampering or cross-feed reuse", () => {
    const codec = new GalleryCursorCodec(SECRET);
    const token = codec.encode("public:feed", { at: "2026-08-02T00:00:00.000Z", id: IMAGE_ID });
    assert.deepEqual(codec.decode("public:feed", token), { at: "2026-08-02T00:00:00.000Z", id: IMAGE_ID });
    assert.throws(() => codec.decode("public:other", token), (error: unknown) => error instanceof GalleryError && error.code === "invalid_cursor");
    assert.throws(() => codec.decode("public:feed", `${token}x`), (error: unknown) => error instanceof GalleryError && error.code === "invalid_cursor");
  });

  it("verifies short-lived signed viewer context and rejects expired identities", () => {
    let now = 1_800_000_000;
    const codec = new InternalViewerContextCodec(SECRET, 300, () => now);
    const signed = codec.issue({ role: "user", userId: 42, requestId: REQUEST_ID }, 60);
    assert.deepEqual(codec.verify({ [USER_CONTEXT_HEADER]: signed.context, [USER_CONTEXT_SIGNATURE_HEADER]: signed.signature }), { role: "user", userId: 42, requestId: REQUEST_ID });
    now += 61;
    assert.throws(() => codec.verify({ [USER_CONTEXT_HEADER]: signed.context, [USER_CONTEXT_SIGNATURE_HEADER]: signed.signature }), (error: unknown) => error instanceof GalleryError && error.statusCode === 401);
  });
});

describe("Phase 6 Gallery configuration and asset URLs", () => {
  it("loads environment-only configuration and rejects weak secrets", () => {
    const env = galleryEnv();
    const config = loadGalleryConfig(env);
    assert.equal(config.port, 3101);
    assert.deepEqual(config.assetHosts, ["cdn.example.test"]);
    assert.throws(() => loadGalleryConfig({ ...env, GALLERY_CURSOR_SECRET: "short" }), /at least 32 bytes/);
  });

  it("allows configured HTTPS public hosts and signs private COS reads", async () => {
    const resolver = new TencentCosGalleryAssetUrlResolver({
      secretId: "id",
      secretKey: "key",
      allowedPublicHosts: ["cdn.example.test"],
      privateUrlTtlSeconds: 300,
      client: { getObjectUrl(_options, callback) { callback(null, { Url: "https://bucket.cos.ap-test.myqcloud.com/private.webp?sign=safe" }); } },
    });
    const asset = { storageProvider: "tencent_cos", bucket: "bucket", region: "ap-test", objectKey: "private.webp", publicUrl: "https://cdn.example.test/public.webp" };
    assert.equal(await resolver.resolve(asset, true), "https://cdn.example.test/public.webp");
    assert.match(await resolver.resolve(asset, false), /sign=safe/);
    await assert.rejects(resolver.resolve({ ...asset, publicUrl: "https://evil.example/public.webp" }, true), (error: unknown) => error instanceof GalleryError && error.code === "service_unavailable");
  });
});

describe("Phase 6 Gallery service", () => {
  it("uses guest feed cache but never caches authenticated viewer flags", async () => {
    const repository = new FakeGalleryRepository();
    const cache = new MemoryGalleryCache();
    const service = serviceFor(repository, cache);
    const guest = viewer("guest");
    await service.listPublic({ limit: 12 }, guest);
    await service.listPublic({ limit: 12 }, guest);
    assert.equal(repository.publicReads, 1);
    await service.listPublic({ limit: 12 }, viewer("user", 9));
    await service.listPublic({ limit: 12 }, viewer("user", 9));
    assert.equal(repository.publicReads, 3);
  });

  it("requires authentication for personal feeds and interactions", async () => {
    const service = serviceFor(new FakeGalleryRepository(), new MemoryGalleryCache());
    await assert.rejects(service.listMine({}, viewer("guest")), (error: unknown) => error instanceof GalleryError && error.code === "authentication_required");
    await assert.rejects(service.setFavorite(IMAGE_ID, true, viewer("guest")), (error: unknown) => error instanceof GalleryError && error.code === "authentication_required");
  });

  it("keeps the public feed cache on interactions and invalidates it on deletion", async () => {
    const cache = new MemoryGalleryCache();
    const service = serviceFor(new FakeGalleryRepository(), cache);
    await service.setFavorite(IMAGE_ID, true, viewer("user", 8));
    assert.equal(cache.versions.get("gallery:public-feed") ?? 0, 0);
    await service.deleteImage(IMAGE_ID, viewer("admin", 1));
    assert.equal(cache.versions.get("gallery:public-feed"), 1);
  });

  it("invalidates only the affected guest detail cache entry", async () => {
    const cache = new MemoryGalleryCache();
    const service = serviceFor(new FakeGalleryRepository(), cache);
    await service.getBySlug("asset-preview", viewer("guest"));
    assert.ok(cache.values.has("gallery:detail:asset-preview"));
    await service.setLike(IMAGE_ID, true, viewer("user", 8));
    assert.equal(cache.values.has("gallery:detail:asset-preview"), false);
  });
});

describe("Phase 6 Gallery HTTP boundary", () => {
  it("requires a signed BFF context and returns sanitized errors", async () => {
    const auth = new InternalViewerContextCodec(SECRET);
    const app = await createGalleryHttpServer({ service: serviceFor(new FakeGalleryRepository(), new MemoryGalleryCache()), auth, logger: silentLogger });
    const unsigned = await app.inject({ method: "GET", url: "/v1/gallery" });
    assert.equal(unsigned.statusCode, 401);
    assert.deepEqual(unsigned.json(), { error: { code: "authentication_required", message: "Valid internal authentication is required" } });

    const signed = auth.issue({ role: "guest", requestId: randomUUID() });
    const ok = await app.inject({ method: "GET", url: "/v1/gallery?limit=5", headers: authHeaders(signed) });
    assert.equal(ok.statusCode, 200);
    assert.equal(ok.json().items.length, 1);

    const invalid = await app.inject({ method: "GET", url: "/v1/gallery?orientation=diagonal", headers: authHeaders(signed) });
    assert.equal(invalid.statusCode, 400);
    assert.equal(invalid.json().error.code, "invalid_request");
    await app.close();
  });
});

describe("Phase 6 deferred COS deletion", () => {
  it("completes successful tasks and records safe retry failures", async () => {
    const repository = new FakeGalleryRepository();
    repository.deletionTasks = [
      { imageId: IMAGE_ID, assets: [{ storageProvider: "test", objectKey: "images/ok.webp" }], attempt: 1 },
      { imageId: "323e4567-e89b-42d3-a456-426614174000", assets: [{ storageProvider: "test", objectKey: "images/fail.webp" }], attempt: 2 },
    ];
    const storage: StorageProvider = {
      code: "test",
      async upload() { throw new Error("unused"); },
      async download() { return Buffer.alloc(0); },
      async delete(key) { if (key.includes("fail")) throw new Error("secret upstream detail"); },
    };
    const result = await new GalleryAssetDeletionWorker({ repository, storageProviders: [storage], logger: silentLogger }).runOnce();
    assert.deepEqual(result, { claimed: 2, completed: 1, failed: 1 });
    assert.deepEqual(repository.completedDeletions, [IMAGE_ID]);
    assert.deepEqual(repository.failedDeletions.map((item) => item.error), ["storage_delete_failed"]);
  });
});

class FakeGalleryRepository implements GalleryRepository {
  publicReads = 0;
  deletionTasks: readonly AssetDeletionTask[] = [];
  completedDeletions: string[] = [];
  failedDeletions: Array<{ imageId: string; error: string }> = [];

  async listPublic() { this.publicReads += 1; return { items: [summary()] }; }
  async listOwned() { return { items: [summary()] }; }
  async listFavorites() { return { items: [summary()] }; }
  async findBySlug(): Promise<GalleryImageDetail> { return detail(); }
  async listSeoImages() { return { items: [{ slug: "asset-preview", publishedAt: "2026-08-02T00:00:00.000Z", assetUrl: "https://assets.example.test/image.webp" }] }; }
  async setFavorite(_imageId: string, _userId: number, active: boolean) { return { active, count: active ? 1 : 0 }; }
  async setLike(_imageId: string, _userId: number, active: boolean) { return { active, count: active ? 1 : 0 }; }
  async softDelete() { return { slug: "asset-preview" }; }
  async createDownloadGrant() { return { url: "https://assets.example.test/image.webp", downloadCount: 1 }; }
  async claimDeletionTasks() { return this.deletionTasks; }
  async completeDeletion(imageId: string) { this.completedDeletions.push(imageId); }
  async failDeletion(imageId: string, safeError: string) { this.failedDeletions.push({ imageId, error: safeError }); }
}

class MemoryGalleryCache implements GalleryCache {
  readonly values = new Map<string, unknown>();
  readonly versions = new Map<string, number>();
  async get<T>(key: string): Promise<T | undefined> { return this.values.get(key) as T | undefined; }
  async set<T>(key: string, value: T): Promise<void> { this.values.set(key, value); }
  async delete(key: string): Promise<void> { this.values.delete(key); }
  async version(namespace: string): Promise<string> { return String(this.versions.get(namespace) ?? 0); }
  async bump(namespace: string): Promise<void> { this.versions.set(namespace, (this.versions.get(namespace) ?? 0) + 1); }
}

function serviceFor(repository: GalleryRepository, cache: GalleryCache): GalleryService {
  return new GalleryService({ repository, cache, cursor: new GalleryCursorCodec(SECRET), logger: silentLogger, cacheTtlSeconds: 30, deletionRetentionSeconds: 86400 });
}

function viewer(role: ViewerContext["role"], userId?: number): ViewerContext {
  return { role, requestId: REQUEST_ID, ...(userId ? { userId } : {}) };
}

function summary(): GalleryImageSummary {
  return {
    id: IMAGE_ID,
    slug: "asset-preview",
    title: "",
    description: "",
    width: 1024,
    height: 1024,
    workflowName: "portrait",
    publishedAt: "2026-08-02T00:00:00.000Z",
    asset: { url: "https://assets.example.test/image.webp", width: 512, height: 512, mimeType: "image/webp", variant: "thumbnail" },
    tags: [],
    likeCount: 0,
    favoriteCount: 0,
    viewerHasLiked: false,
    viewerHasFavorited: false,
  };
}

function detail(): GalleryImageDetail {
  return { ...summary(), providerCode: "comfyui", createdAt: "2026-08-02T00:00:00.000Z", downloadCount: 0, canDelete: false, isOwner: false };
}

function authHeaders(signed: { readonly context: string; readonly signature: string }): Record<string, string> {
  return { [USER_CONTEXT_HEADER]: signed.context, [USER_CONTEXT_SIGNATURE_HEADER]: signed.signature };
}

const silentLogger: StructuredLogger = { info() {}, error() {} };

function galleryEnv(): NodeJS.ProcessEnv {
  return {
    DATABASE_URL: "postgresql://gallery:secret@db.internal/gallery",
    GALLERY_CURSOR_SECRET: SECRET,
    GALLERY_INTERNAL_HMAC_SECRET: `${SECRET}-internal`,
    GALLERY_ASSET_HOSTS: "cdn.example.test",
    COS_SECRET_ID: "secret-id",
    COS_SECRET_KEY: "secret-key",
    COS_BUCKET: "bucket-123",
    COS_REGION: "ap-guangzhou",
  };
}
