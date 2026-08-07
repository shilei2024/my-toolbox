import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, it } from "node:test";
import { AdminService } from "../src/admin/admin-service.ts";
import type { AdminRepository } from "../src/admin/repository.ts";
import type { AdminDashboard, AdminImageItem, AdminProviderItem, AdminProviderModelItem, AdminWorkflowItem } from "../src/admin/types.ts";
import { NoopGalleryCache } from "../src/gallery/cache.ts";
import { GalleryCursorCodec } from "../src/gallery/cursor.ts";
import { GalleryError } from "../src/gallery/errors.ts";
import { GalleryService } from "../src/gallery/gallery-service.ts";
import { createGalleryHttpServer } from "../src/gallery/http-server.ts";
import { InternalViewerContextCodec, USER_CONTEXT_HEADER, USER_CONTEXT_SIGNATURE_HEADER } from "../src/gallery/internal-auth.ts";
import type { GalleryRepository } from "../src/gallery/repository.ts";
import type { AssetDeletionTask, GalleryImageDetail, GalleryImageSummary, ViewerContext } from "../src/gallery/types.ts";
import type { StructuredLogger } from "../src/pipeline/structured-logger.ts";

const SECRET = "phase-eight-test-secret-that-is-long-enough-123";
const IMAGE_ID = "e23e4567-e89b-42d3-a456-426614174000";
const PROVIDER_ID = "e33e4567-e89b-42d3-a456-426614174000";
const WORKFLOW_ID = "e43e4567-e89b-42d3-a456-426614174000";
const UPDATED_AT = "2026-08-02T00:00:00.000Z";

describe("Phase 8 Admin service", () => {
  it("enforces backend admin RBAC independently of the frontend", async () => {
    const service = adminFor(new FakeAdminRepository());
    await assert.rejects(service.dashboard(viewer("guest")), (error: unknown) => error instanceof GalleryError && error.statusCode === 401);
    await assert.rejects(service.dashboard(viewer("user", 7)), (error: unknown) => error instanceof GalleryError && error.statusCode === 403);
    assert.equal((await service.dashboard(viewer("admin", 1))).providers[0]?.secretConfigured, true);
  });

  it("validates mutations, invalidates Gallery after moderation and logs only safe fields", async () => {
    const repository = new FakeAdminRepository();
    let invalidations = 0;
    const service = new AdminService({ repository, logger: silentLogger, onContentChanged: async () => { invalidations += 1; } });
    await assert.rejects(service.moderateImage(IMAGE_ID, { decision: "approved", reasonCodes: [], expectedUpdatedAt: "bad" }, viewer("admin", 1)), (error: unknown) => error instanceof GalleryError && error.code === "invalid_request");
    const result = await service.moderateImage(IMAGE_ID, { decision: "approved", reasonCodes: ["safe"], expectedUpdatedAt: UPDATED_AT }, viewer("admin", 1));
    assert.equal(result.moderationStatus, "approved");
    assert.equal(invalidations, 1);
  });

  it("protects Admin HTTP routes with signed role context", async () => {
    const auth = new InternalViewerContextCodec(SECRET);
    const gallery = galleryService();
    const app = await createGalleryHttpServer({ service: gallery, admin: adminFor(new FakeAdminRepository()), auth, logger: silentLogger });
    const user = auth.issue(viewer("user", 8));
    const forbidden = await app.inject({ method: "GET", url: "/v1/admin/dashboard", headers: authHeaders(user) });
    assert.equal(forbidden.statusCode, 403);
    const admin = auth.issue(viewer("admin", 1));
    const ok = await app.inject({ method: "GET", url: "/v1/admin/dashboard", headers: authHeaders(admin) });
    assert.equal(ok.statusCode, 200);
    assert.equal(ok.json().overview.pendingModeration, 1);
    const patch = await app.inject({ method: "PATCH", url: `/v1/admin/providers/${PROVIDER_ID}`, headers: authHeaders(admin), payload: { status: "disabled", priority: 10, expectedUpdatedAt: UPDATED_AT } });
    assert.equal(patch.statusCode, 200);
    assert.equal(patch.json().status, "disabled");
    await app.close();
  });
});

class FakeAdminRepository implements AdminRepository {
  async dashboard(): Promise<AdminDashboard> { return dashboard(); }
  async moderateImage(_id: string, command: { decision: "approved" | "rejected" }): Promise<AdminImageItem> { return { ...dashboard().moderationQueue[0]!, moderationStatus: command.decision }; }
  async updateProvider(_id: string, command: { status: "active" | "disabled"; priority: number }): Promise<AdminProviderItem> { return { ...dashboard().providers[0]!, status: command.status, priority: command.priority }; }
  async updateProviderModel(_id: string, command: { tier: "free" | "member" }): Promise<AdminProviderModelItem> { return { ...dashboard().providers[0]!.models[0]!, tier: command.tier }; }
  async updateWorkflow(_id: string, command: { isEnabled: boolean; sortOrder: number }): Promise<AdminWorkflowItem> { return { ...dashboard().workflows[0]!, isEnabled: command.isEnabled, sortOrder: command.sortOrder }; }
}

function dashboard(): AdminDashboard {
  return {
    overview: { pendingModeration: 1, publicImages: 4, jobsLast24Hours: 3, failedJobsLast24Hours: 0, activeProviders: 1, enabledWorkflows: 1 },
    moderationQueue: [{ id: IMAGE_ID, slug: "review-me", title: "Review me", workflowName: "Portrait", moderationStatus: "manual_review", visibility: "public", promptVisibility: "hidden", thumbnailUrl: "https://assets.example.test/review.webp", createdAt: UPDATED_AT, updatedAt: UPDATED_AT }],
    providers: [{ id: PROVIDER_ID, code: "comfyui", displayName: "ComfyUI", adapterType: "comfyui", status: "active", priority: 10, secretConfigured: true, consecutiveFailures: 0, updatedAt: UPDATED_AT, models: [{ id: "model-1", providerId: PROVIDER_ID, modelCode: "comfyui-v1", displayName: "ComfyUI v1", tier: "free", isDefault: true, isEnabled: true, updatedAt: UPDATED_AT }] }],
    workflows: [{ id: WORKFLOW_ID, slug: "portrait", name: "Portrait", category: "people", isEnabled: true, sortOrder: 10, activeVersion: 1, bindingCount: 1, updatedAt: UPDATED_AT }],
    recentJobs: [],
    recentAudit: [],
  };
}

function adminFor(repository: AdminRepository): AdminService { return new AdminService({ repository, logger: silentLogger, onContentChanged: async () => {} }); }
function viewer(role: ViewerContext["role"], userId?: number): ViewerContext { return { role, requestId: randomUUID(), ...(userId ? { userId } : {}) }; }
function authHeaders(value: { context: string; signature: string }): Record<string, string> { return { [USER_CONTEXT_HEADER]: value.context, [USER_CONTEXT_SIGNATURE_HEADER]: value.signature }; }

function galleryService(): GalleryService { return new GalleryService({ repository: new FakeGalleryRepository(), cursor: new GalleryCursorCodec(SECRET), cache: new NoopGalleryCache(), logger: silentLogger, cacheTtlSeconds: 30, deletionRetentionSeconds: 86400 }); }
class FakeGalleryRepository implements GalleryRepository {
  async listPublic() { return { items: [summary()] }; }
  async listOwned() { return { items: [summary()] }; }
  async listFavorites() { return { items: [summary()] }; }
  async listSeoImages() { return { items: [] }; }
  async findBySlug(): Promise<GalleryImageDetail> { return { ...summary(), providerCode: "comfyui", createdAt: UPDATED_AT, downloadCount: 0, canDelete: false, isOwner: false }; }
  async setFavorite(_a: string, _b: number, active: boolean) { return { active, count: 0 }; }
  async setLike(_a: string, _b: number, active: boolean) { return { active, count: 0 }; }
  async softDelete() { return { slug: "review-me" }; }
  async createDownloadGrant() { return { url: "https://assets.example.test/review.webp", downloadCount: 0 }; }
  async claimDeletionTasks(): Promise<readonly AssetDeletionTask[]> { return []; }
  async completeDeletion() {}
  async failDeletion() {}
}
function summary(): GalleryImageSummary { return { id: IMAGE_ID, slug: "review-me", title: "Review me", description: "", width: 512, height: 512, workflowName: "Portrait", publishedAt: UPDATED_AT, asset: { url: "https://assets.example.test/review.webp", width: 512, height: 512, mimeType: "image/webp", variant: "thumbnail" }, tags: [], likeCount: 0, favoriteCount: 0, viewerHasLiked: false, viewerHasFavorited: false }; }
const silentLogger: StructuredLogger = { info() {}, error() {} };
