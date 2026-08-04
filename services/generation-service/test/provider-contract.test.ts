import assert from "node:assert/strict";
import test from "node:test";

import {
  MockImageProvider,
  NoEligibleProviderError,
  ProviderError,
  ProviderRegistry,
  ProviderSelectionPolicy,
  normalizeProviderError,
  type GenerationRequest,
  type ProviderBinding,
  type ProviderCallContext,
} from "../src/providers/index.ts";

const request: GenerationRequest = {
  jobId: "job-1",
  workflow: {
    workflowId: "workflow-1",
    workflowVersionId: "workflow-version-1",
    version: 1,
    kind: "portrait",
  },
  mode: "text-to-image",
  prompt: "A quiet garden in the morning",
  negativePrompt: "blur",
  width: 1024,
  height: 1024,
  count: 1,
  seed: 42,
  parameters: { style: "editorial" },
};

const context: ProviderCallContext = {
  requestId: "request-1",
  attemptId: "attempt-1",
};

function binding(
  providerCode: string,
  overrides: Partial<ProviderBinding> = {},
): ProviderBinding {
  return {
    id: `binding-${providerCode}`,
    providerCode,
    workflowVersionId: request.workflow.workflowVersionId,
    providerConfig: {},
    priority: 100,
    estimatedCost: 0,
    timeoutSeconds: 300,
    maxAttempts: 2,
    enabled: true,
    ...overrides,
  };
}

test("frontend-facing generation request has no provider routing field", () => {
  assert.equal("provider" in request, false);
  assert.equal("providerCode" in request, false);
  assert.equal("apiKey" in request, false);
});

test("registry rejects duplicate providers and resolves by stable code", () => {
  const registry = new ProviderRegistry();
  const provider = new MockImageProvider();
  registry.register(provider);

  assert.equal(registry.get("mock"), provider);
  assert.throws(() => registry.register(new MockImageProvider()), /already registered/);
  assert.throws(() => registry.get("missing"), /not registered/);
});

test("selection policy filters capabilities and ranks active providers deterministically", () => {
  const registry = new ProviderRegistry();
  registry.register(new MockImageProvider({ code: "cheap", priority: 20 }));
  registry.register(new MockImageProvider({ code: "preferred", priority: 5 }));
  registry.register(new MockImageProvider({ code: "degraded", availability: "degraded", priority: 1 }));
  registry.register(new MockImageProvider({ code: "disabled", availability: "disabled" }));
  const policy = new ProviderSelectionPolicy(registry);

  const ranked = policy.rank(request, [
    binding("cheap", { estimatedCost: 0.001 }),
    binding("preferred", { estimatedCost: 0.02 }),
    binding("degraded", { priority: 1 }),
    binding("disabled"),
    binding("missing"),
  ]);

  assert.deepEqual(
    ranked.map(({ provider }) => provider.descriptor.code),
    ["preferred", "cheap", "degraded"],
  );
  assert.equal(policy.select(request, ranked.map(({ binding: item }) => item)).provider.descriptor.code, "preferred");
});

test("selection policy rejects requests outside every provider capability", () => {
  const registry = new ProviderRegistry();
  registry.register(new MockImageProvider());
  const policy = new ProviderSelectionPolicy(registry);
  const oversized = { ...request, width: 8192 };

  assert.throws(() => policy.select(oversized, [binding("mock")]), NoEligibleProviderError);
});

test("mock provider satisfies synchronous generation, health and cost contracts", async () => {
  const provider = new MockImageProvider();
  const submission = await provider.generate(
    request,
    binding("mock", { providerWorkflowRef: "portrait-v1", providerModel: "mock-v1" }),
    context,
  );
  const health = await provider.healthCheck(context);
  const cost = await provider.estimateCost(request, binding("mock"));

  assert.equal(submission.state, "succeeded");
  assert.equal(submission.outputs.length, 1);
  assert.equal(submission.outputs[0]?.kind, "base64");
  assert.equal(submission.outputs[0]?.width, 1024);
  assert.equal(submission.providerMetadata.workflowRef, "portrait-v1");
  assert.equal(health.healthy, true);
  assert.deepEqual(cost, { amount: 0, currency: "USD", estimated: true });
});

test("mock provider supports asynchronous polling and cancellation", async () => {
  let now = 1_000;
  const provider = new MockImageProvider({ asynchronous: true, latencyMs: 100, now: () => now });
  const first = await provider.generate(request, binding("mock"), context);
  assert.equal(first.state, "queued");

  const running = await provider.getStatus(first.externalRequestId, context);
  assert.equal(running.state, "running");

  now = 1_101;
  const completed = await provider.getStatus(first.externalRequestId, context);
  assert.equal(completed.state, "succeeded");
  assert.equal(completed.outputs.length, 1);

  const second = await provider.generate(
    request,
    binding("mock"),
    { ...context, attemptId: "attempt-2" },
  );
  const cancellation = await provider.cancel(second.externalRequestId, context);
  const cancelled = await provider.getStatus(second.externalRequestId, context);
  assert.equal(cancellation.accepted, true);
  assert.equal(cancelled.state, "cancelled");
});

test("provider errors expose stable safe fields and retry semantics", () => {
  const rateLimit = new ProviderError({
    providerCode: "mock",
    category: "rate_limit",
    code: "too_many_requests",
    message: "Provider is temporarily rate limited",
    statusCode: 429,
  });
  assert.equal(rateLimit.retryable, true);
  assert.deepEqual(rateLimit.toSafeRecord(), {
    providerCode: "mock",
    category: "rate_limit",
    code: "too_many_requests",
    message: "Provider is temporarily rate limited",
    retryable: true,
    externalRequestId: undefined,
    statusCode: 429,
  });

  const raw = new Error("secret token must never leak");
  const normalized = normalizeProviderError(raw, "mock");
  assert.equal(normalized.category, "unknown");
  assert.equal(normalized.retryable, false);
  assert.equal(normalized.message.includes("secret token"), false);
});

test("aborted calls are normalized as non-retryable cancellation", () => {
  const error = normalizeProviderError(new DOMException("aborted", "AbortError"), "mock");
  assert.equal(error.category, "cancelled");
  assert.equal(error.retryable, false);
});
