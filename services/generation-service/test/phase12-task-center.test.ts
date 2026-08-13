import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { GalleryCursorCodec } from "../src/gallery/cursor.ts";
import { createGalleryHttpServer } from "../src/gallery/http-server.ts";
import { InternalViewerContextCodec, USER_CONTEXT_HEADER, USER_CONTEXT_SIGNATURE_HEADER } from "../src/gallery/internal-auth.ts";
import { GenerationService } from "../src/generation/generation-service.ts";
import type { GenerationRepository } from "../src/generation/repository.ts";
import type { GenerationPageResult, GenerationView } from "../src/generation/types.ts";
import { generationTaskCenter } from "../src/tasks/task-center-service.ts";

const generation: GenerationView = {
  id: "00000000-0000-4000-8000-000000000012", status: "completed", workflowSlug: "portrait-v1", workflowName: "质感人像", mode: "workflow",
  prompt: "晨光庭院", negativePrompt: "", width: 1024, height: 1024, count: 1, visibility: "private", promptVisibility: "hidden",
  creditsReserved: "2.0000", creditsCharged: "2.0000", creditTier: "free", cancelRequested: false,
  createdAt: "2026-08-09T00:00:00.000Z", updatedAt: "2026-08-09T00:01:00.000Z", finishedAt: "2026-08-09T00:01:00.000Z",
  mediaType: "image", images: [{ id: "image-1", slug: "m3-task-output" }], outputs: [],
};

class TaskRepository implements GenerationRepository {
  async listWorkflows() { return []; }
  async create() { return generation; }
  async findForViewer(id: string) { return id === generation.id ? generation : undefined; }
  async listForViewer(): Promise<GenerationPageResult> { return { items: [generation] }; }
  async requestCancellation() { return undefined; }
  async finalizeCancellation() { return undefined; }
}

const viewer = { role: "user" as const, userId: 9, requestId: "00000000-0000-4000-8000-000000000009" };

describe("M3 task center", () => {
  it("maps the durable generation task into a module-neutral summary", async () => {
    const generationService = new GenerationService({ repository: new TaskRepository(), cursor: new GalleryCursorCodec("task-center-cursor-secret-1234567890") });
    const tasks = generationTaskCenter(generationService);
    const page = await tasks.list({ limit: 12 }, viewer);
    assert.deepEqual(page.items, [{
      key: `generation:${generation.id}`, module: "generation", sourceId: generation.id, title: generation.workflowName,
      mediaType: "image",
      status: "completed", createdAt: generation.createdAt, updatedAt: generation.updatedAt, finishedAt: generation.finishedAt,
      cancelRequested: false, creditsReserved: "2.0000", creditsCharged: "2.0000", outputLinks: generation.images.map((image) => ({ ...image, mediaType: "image" })),
    }]);
  });

  it("keeps task history authenticated and rejects an unknown source module", async () => {
    const tasks = generationTaskCenter(new GenerationService({ repository: new TaskRepository() }));
    await assert.rejects(tasks.list({}, { role: "guest", requestId: viewer.requestId }), { code: "authentication_required" });
    await assert.rejects(tasks.list({ module: "video" as never }, viewer), { code: "invalid_request" });
  });

  it("exposes the signed HTTP task-center contract", async () => {
    const auth = new InternalViewerContextCodec("task-center-http-secret-1234567890");
    const generationService = new GenerationService({ repository: new TaskRepository() });
    const app = await createGalleryHttpServer({ service: {} as never, auth, tasks: generationTaskCenter(generationService), logger: { info() {}, error() {} } });
    const user = auth.issue({ role: "user", userId: 9 });
    const response = await app.inject({ method: "GET", url: "/v1/tasks?limit=12", headers: { [USER_CONTEXT_HEADER]: user.context, [USER_CONTEXT_SIGNATURE_HEADER]: user.signature } });
    assert.equal(response.statusCode, 200);
    assert.equal(response.json().items[0]?.key, `generation:${generation.id}`);
    const guest = auth.issue({ role: "guest" });
    const rejected = await app.inject({ method: "GET", url: "/v1/tasks", headers: { [USER_CONTEXT_HEADER]: guest.context, [USER_CONTEXT_SIGNATURE_HEADER]: guest.signature } });
    assert.equal(rejected.statusCode, 401);
    await app.close();
  });
});
