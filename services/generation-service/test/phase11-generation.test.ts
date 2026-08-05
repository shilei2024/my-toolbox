import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { GalleryCursorCodec, type DecodedCursor } from "../src/gallery/cursor.ts";
import { GenerationError } from "../src/generation/errors.ts";
import { GenerationService } from "../src/generation/generation-service.ts";
import { clampToBounds, workflowBounds, workflowSizePresets } from "../src/generation/workflow-options.ts";
import { createGalleryHttpServer } from "../src/gallery/http-server.ts";
import { InternalViewerContextCodec, USER_CONTEXT_HEADER, USER_CONTEXT_SIGNATURE_HEADER } from "../src/gallery/internal-auth.ts";
import type { GenerationRepository } from "../src/generation/repository.ts";
import { parseDefaultModeration, type CancelGenerationResult, type CreateGenerationInput, type GenerationPageResult, type GenerationView, type GenerationWorkflowView } from "../src/generation/types.ts";

const generation: GenerationView = {
  id: "job-1", status: "pending", workflowSlug: "portrait-v1", workflowName: "质感人像",
  prompt: "清晨的庭院", negativePrompt: "", width: 1024, height: 1024, count: 1, visibility: "private", promptVisibility: "hidden",
  creditsReserved: "1.0000", creditsCharged: "0.0000", cancelRequested: false,
  createdAt: "2026-08-03T00:00:00.000Z", updatedAt: "2026-08-03T00:00:00.000Z", images: [],
};

class FakeRepository implements GenerationRepository {
  created?: CreateGenerationInput;
  cancelled?: string;
  page: GenerationPageResult = { items: [] };
  listWorkflows(defaultCreditCost: string): Promise<readonly GenerationWorkflowView[]> {
    return Promise.resolve([{
      slug: "portrait-v1", name: "质感人像", description: "", category: "portrait",
      defaults: { width: 1024, height: 1024, count: 1, visibility: "private" },
      countRange: { min: 1, max: 4 },
      sizes: [
        { width: 1024, height: 1024 }, { width: 768, height: 1024 }, { width: 1024, height: 768 },
        { width: 768, height: 1344 }, { width: 1344, height: 768 }, { width: 832, height: 1248 }, { width: 1248, height: 832 },
      ],
      creditCost: defaultCreditCost,
    }]);
  }
  create(input: CreateGenerationInput): Promise<GenerationView> { this.created = input; return Promise.resolve(generation); }
  findForViewer(id: string): Promise<GenerationView | undefined> { return Promise.resolve(id === generation.id ? generation : undefined); }
  listForViewer(_userId: number, cursor: DecodedCursor | undefined, _limit: number): Promise<GenerationPageResult> { return Promise.resolve(cursor ? { items: [] } : this.page); }
  requestCancellation(id: string): Promise<CancelGenerationResult | undefined> { this.cancelled = id; return Promise.resolve(id === generation.id ? { generation: { ...generation, status: "cancelled" }, accepted: true, signalWorker: false } : undefined); }
}

const viewer = { role: "user" as const, userId: 7, requestId: "00000000-0000-4000-8000-000000000007" };
const validBody = { workflowSlug: "portrait-v1", prompt: "清晨的庭院", negativePrompt: "", width: 1024, height: 1024, count: 1, visibility: "private", promptVisibility: "hidden", parameters: {} };

describe("M1 generation API domain", () => {
  it("creates a provider-agnostic job and keeps identity server-side", async () => {
    const repository = new FakeRepository();
    const service = new GenerationService({ repository, defaultCreditCost: "2" });
    assert.deepEqual(await service.create(validBody, "create-attempt-1", viewer), generation);
    assert.equal(repository.created?.userId, 7);
    assert.equal(repository.created?.idempotencyKey, "create-attempt-1");
    assert.equal("provider" in validBody, false);
    assert.equal((await service.listWorkflows())[0]?.creditCost, "2.0000");
  });

  it("rejects guests, unknown fields and unsafe dimensions", async () => {
    const service = new GenerationService({ repository: new FakeRepository() });
    await assert.rejects(service.create(validBody, "create-attempt-1", { role: "guest", requestId: viewer.requestId }), (error) => error instanceof GenerationError && error.code === "authentication_required");
    await assert.rejects(service.create({ ...validBody, provider: "openai" }, "create-attempt-1", viewer), (error) => error instanceof GenerationError && error.code === "invalid_request");
    await assert.rejects(service.create({ ...validBody, width: 16 }, "create-attempt-1", viewer), (error) => error instanceof GenerationError && error.code === "invalid_request");
  });

  it("queries only through viewer-scoped repository methods and cancels idempotently", async () => {
    const repository = new FakeRepository(); const service = new GenerationService({ repository });
    assert.equal((await service.get("job-1", viewer)).id, "job-1");
    assert.equal((await service.cancel("job-1", viewer)).accepted, true);
    assert.equal(repository.cancelled, "job-1");
    await assert.rejects(service.get("job-missing", viewer), (error) => error instanceof GenerationError && error.statusCode === 404);
  });

  it("lists viewer-scoped tasks with signed cursor pagination and strict query validation", async () => {
    const codec = new GalleryCursorCodec("generation-cursor-test-secret-1234567890");
    const repository = new FakeRepository();
    repository.page = { items: [generation], next: { at: generation.createdAt, id: "00000000-0000-4000-8000-000000000099" } };
    const service = new GenerationService({ repository, cursor: codec });
    const first = await service.list({ limit: 1 }, viewer);
    assert.equal(first.items[0]?.id, "job-1");
    assert.ok(first.nextCursor);
    const second = await service.list({ limit: 1, cursor: first.nextCursor }, viewer);
    assert.deepEqual(second.items, []);
    await assert.rejects(service.list({ limit: 0 }, viewer), (error) => error instanceof GenerationError && error.code === "invalid_request");
    await assert.rejects(service.list({ status: "queued" as never }, viewer), (error) => error instanceof GenerationError && error.code === "invalid_request");
    await assert.rejects(service.list({}, { role: "guest", requestId: viewer.requestId }), (error) => error instanceof GenerationError && error.code === "authentication_required");
    await assert.rejects(service.list({ cursor: "tampered.cursor" }, viewer), (error) => error instanceof GenerationError && error.code === "invalid_cursor");
  });

  it("fails closed for invalid credit configuration", () => {
    assert.throws(() => new GenerationService({ repository: new FakeRepository(), defaultCreditCost: "-1" }), /GENERATION_DEFAULT_CREDIT_COST/);
  });

  it("fails fast with 503 when the generation queue is not configured", async () => {
    const service = new GenerationService({ repository: new FakeRepository(), ready: false });
    await assert.rejects(
      service.create(validBody, "create-attempt-1", viewer),
      (error) => error instanceof GenerationError && error.code === "generation_queue_not_configured" && error.statusCode === 503,
    );
  });

  it("parses the default moderation policy fail-closed", () => {
    assert.equal(parseDefaultModeration(undefined), "pending");
    assert.equal(parseDefaultModeration("approved"), "approved");
    assert.equal(parseDefaultModeration("APPROVED"), "approved");
    assert.throws(() => parseDefaultModeration("auto"), /GALLERY_DEFAULT_MODERATION/);
  });

  it("derives per-workflow count bounds and size presets from the input schema", () => {
    const schema = {
      type: "object",
      properties: {
        width: { type: "integer", minimum: 1000, maximum: 1100 },
        height: { type: "integer", minimum: 1000, maximum: 1100 },
        count: { type: "integer", minimum: 1, maximum: 1 },
      },
    };
    const bounds = workflowBounds(schema);
    assert.deepEqual(bounds.count, { min: 1, max: 1 });
    assert.equal(bounds.width.min, 1000);
    assert.equal(bounds.width.max, 1100);
    assert.equal(clampToBounds(4, bounds.count), 1);
    const sizes = workflowSizePresets(bounds, { width: 1024, height: 1024 });
    assert.equal(sizes.length, 1);
    assert.deepEqual(sizes[0], { width: 1024, height: 1024 });
    assert.deepEqual(workflowBounds({ properties: { count: { minimum: 2, maximum: 6 } } }).count, { min: 2, max: 6 });
  });

  it("exposes the signed internal HTTP contract and returns 202 for durable creation", async () => {
    const auth = new InternalViewerContextCodec("generation-http-test-secret-1234567890");
    const service = new GenerationService({ repository: new FakeRepository() });
    const app = await createGalleryHttpServer({ service: {} as never, auth, generation: service, logger: { info() {}, error() {} } });
    const guest = auth.issue({ role: "guest" });
    const workflows = await app.inject({ method: "GET", url: "/v1/generation/workflows", headers: { [USER_CONTEXT_HEADER]: guest.context, [USER_CONTEXT_SIGNATURE_HEADER]: guest.signature } });
    assert.equal(workflows.statusCode, 200);
    const user = auth.issue({ role: "user", userId: 7 });
    const created = await app.inject({ method: "POST", url: "/v1/generations", headers: { [USER_CONTEXT_HEADER]: user.context, [USER_CONTEXT_SIGNATURE_HEADER]: user.signature, "idempotency-key": "create-attempt-http-1" }, payload: validBody });
    assert.equal(created.statusCode, 202);
    assert.equal(created.json().id, generation.id);
    const listed = await app.inject({ method: "GET", url: "/v1/generations?limit=8", headers: { [USER_CONTEXT_HEADER]: user.context, [USER_CONTEXT_SIGNATURE_HEADER]: user.signature } });
    assert.equal(listed.statusCode, 200);
    assert.deepEqual(listed.json(), { items: [] });
    const listedAsGuest = await app.inject({ method: "GET", url: "/v1/generations", headers: { [USER_CONTEXT_HEADER]: guest.context, [USER_CONTEXT_SIGNATURE_HEADER]: guest.signature } });
    assert.equal(listedAsGuest.statusCode, 401);
    await app.close();
  });
});
