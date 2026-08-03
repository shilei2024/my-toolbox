import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { GenerationError } from "../src/generation/errors.ts";
import { GenerationService } from "../src/generation/generation-service.ts";
import { createGalleryHttpServer } from "../src/gallery/http-server.ts";
import { InternalViewerContextCodec, USER_CONTEXT_HEADER, USER_CONTEXT_SIGNATURE_HEADER } from "../src/gallery/internal-auth.ts";
import type { GenerationRepository } from "../src/generation/repository.ts";
import type { CancelGenerationResult, CreateGenerationInput, GenerationView, GenerationWorkflowView } from "../src/generation/types.ts";

const generation: GenerationView = {
  id: "job-1", status: "pending", workflowSlug: "portrait-v1", workflowName: "质感人像",
  width: 1024, height: 1024, count: 1, visibility: "private", promptVisibility: "hidden",
  creditsReserved: "1.0000", creditsCharged: "0.0000", cancelRequested: false,
  createdAt: "2026-08-03T00:00:00.000Z", updatedAt: "2026-08-03T00:00:00.000Z", images: [],
};

class FakeRepository implements GenerationRepository {
  created?: CreateGenerationInput;
  cancelled?: string;
  listWorkflows(defaultCreditCost: string): Promise<readonly GenerationWorkflowView[]> {
    return Promise.resolve([{ slug: "portrait-v1", name: "质感人像", description: "", category: "portrait", defaults: { width: 1024, height: 1024, count: 1, visibility: "private" }, creditCost: defaultCreditCost }]);
  }
  create(input: CreateGenerationInput): Promise<GenerationView> { this.created = input; return Promise.resolve(generation); }
  findForViewer(id: string): Promise<GenerationView | undefined> { return Promise.resolve(id === generation.id ? generation : undefined); }
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

  it("fails closed for invalid credit configuration", () => {
    assert.throws(() => new GenerationService({ repository: new FakeRepository(), defaultCreditCost: "-1" }), /GENERATION_DEFAULT_CREDIT_COST/);
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
    await app.close();
  });
});
