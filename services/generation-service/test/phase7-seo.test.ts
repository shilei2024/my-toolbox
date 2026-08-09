import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, it } from "node:test";
import type { StructuredLogger } from "../src/pipeline/structured-logger.ts";
import type { GalleryCache } from "../src/gallery/cache.ts";
import { NoopGalleryCache } from "../src/gallery/cache.ts";
import { GalleryCursorCodec } from "../src/gallery/cursor.ts";
import { GalleryError } from "../src/gallery/errors.ts";
import { GalleryService } from "../src/gallery/gallery-service.ts";
import { createGalleryHttpServer } from "../src/gallery/http-server.ts";
import { InternalViewerContextCodec, USER_CONTEXT_HEADER, USER_CONTEXT_SIGNATURE_HEADER } from "../src/gallery/internal-auth.ts";
import type { GalleryRepository } from "../src/gallery/repository.ts";
import type { AssetDeletionTask, GalleryImageDetail, GalleryImageSummary } from "../src/gallery/types.ts";

const SECRET = "phase-seven-test-secret-that-is-long-enough-123";
const IMAGE_ID = "923e4567-e89b-42d3-a456-426614174000";

describe("Phase 7 SEO feed", () => {
  it("returns only the minimal sitemap contract with a scoped signed cursor", async () => {
    const repository = new SeoRepository();
    const service = serviceFor(repository, new NoopGalleryCache());
    const first = await service.listSeoImages({ limit: 1 });
    assert.deepEqual(first.items, [{ slug: "public-artwork", publishedAt: "2026-08-02T00:00:00.000Z", assetUrl: "https://assets.example.test/public.webp" }]);
    assert.ok(first.nextCursor);
    assert.equal("title" in first.items[0]!, false);
    await assert.rejects(service.listSeoImages({ cursor: `${first.nextCursor}x` }), (error: unknown) => error instanceof GalleryError && error.code === "invalid_cursor");
  });

  it("keeps the SEO feed behind signed service authentication and rate-safe limits", async () => {
    const auth = new InternalViewerContextCodec(SECRET);
    const app = await createGalleryHttpServer({ service: serviceFor(new SeoRepository(), new NoopGalleryCache()), auth, logger: silentLogger });
    assert.equal((await app.inject({ method: "GET", url: "/v1/seo/images" })).statusCode, 401);
    const signed = auth.issue({ role: "guest", requestId: randomUUID() });
    const headers = { [USER_CONTEXT_HEADER]: signed.context, [USER_CONTEXT_SIGNATURE_HEADER]: signed.signature };
    const ok = await app.inject({ method: "GET", url: "/v1/seo/images?limit=500", headers });
    assert.equal(ok.statusCode, 200);
    assert.equal(ok.json().items[0].slug, "public-artwork");
    const oversized = await app.inject({ method: "GET", url: "/v1/seo/images?limit=5001", headers });
    assert.equal(oversized.statusCode, 400);
    await app.close();
  });
});

class SeoRepository implements GalleryRepository {
  async listSeoImages(cursor: { readonly at: string; readonly id: string } | undefined) {
    if (cursor) return { items: [] };
    return {
      items: [{ slug: "public-artwork", publishedAt: "2026-08-02T00:00:00.000Z", assetUrl: "https://assets.example.test/public.webp" }],
      next: { at: "2026-08-02T00:00:00.000Z", id: IMAGE_ID },
    };
  }
  async listPublic() { return { items: [summary()] }; }
  async listOwned() { return { items: [summary()] }; }
  async listFavorites() { return { items: [summary()] }; }
  async findBySlug(): Promise<GalleryImageDetail> { return { ...summary(), providerCode: "comfyui", createdAt: "2026-08-02T00:00:00.000Z", downloadCount: 0, canDelete: false, isOwner: false }; }
  async setFavorite(_imageId: string, _userId: number, active: boolean) { return { active, count: Number(active) }; }
  async setLike(_imageId: string, _userId: number, active: boolean) { return { active, count: Number(active) }; }
  async softDelete() { return { slug: "public-artwork" }; }
  async createDownloadGrant() { return { url: "https://assets.example.test/public.webp", downloadCount: 1 }; }
  async claimDeletionTasks(): Promise<readonly AssetDeletionTask[]> { return []; }
  async completeDeletion() {}
  async failDeletion() {}
}

function serviceFor(repository: GalleryRepository, cache: GalleryCache): GalleryService {
  return new GalleryService({ repository, cursor: new GalleryCursorCodec(SECRET), cache, logger: silentLogger, cacheTtlSeconds: 30, deletionRetentionSeconds: 86_400 });
}

function summary(): GalleryImageSummary {
  return { id: IMAGE_ID, slug: "public-artwork", title: "", description: "", width: 1024, height: 1024, workflowName: "portrait", publishedAt: "2026-08-02T00:00:00.000Z", asset: { url: "https://assets.example.test/public.webp", width: 512, height: 512, mimeType: "image/webp", variant: "thumbnail" }, tags: [], likeCount: 0, favoriteCount: 0, viewerHasLiked: false, viewerHasFavorited: false };
}

const silentLogger: StructuredLogger = { info() {}, error() {} };
