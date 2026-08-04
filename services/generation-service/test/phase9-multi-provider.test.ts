import assert from "node:assert/strict";
import test from "node:test";

import { ConfigurationError } from "../src/config.ts";
import { ProviderError } from "../src/providers/errors.ts";
import { MockImageProvider } from "../src/providers/mock.provider.ts";
import { MultiProviderExecutor } from "../src/providers/multi-provider-executor.ts";
import { ProviderRegistry } from "../src/providers/registry.ts";
import { ProviderSelectionPolicy } from "../src/providers/selection-policy.ts";
import type { GenerationRequest, ProviderBinding, ProviderCallContext } from "../src/providers/types.ts";
import { loadPhase9RemoteProviderConfig } from "../src/remote-providers/config.ts";
import { GeminiImageProvider } from "../src/remote-providers/gemini.ts";
import { JimengImageProvider } from "../src/remote-providers/jimeng.ts";
import { OpenAIImageProvider } from "../src/remote-providers/openai.ts";

const PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
const context: ProviderCallContext = { requestId: "request-phase9", attemptId: "attempt-phase9" };
const request: GenerationRequest = {
  jobId: "job-phase9", workflow: { workflowId: "portrait", workflowVersionId: "version-phase9", version: 1, kind: "portrait" },
  mode: "text-to-image", prompt: "A calm editorial portrait", negativePrompt: "blur", width: 1024, height: 1024, count: 1, parameters: {},
};

test("Phase 9 configuration enables only credentialed providers and requires explicit endpoints", () => {
  assert.deepEqual(loadPhase9RemoteProviderConfig({}), {});
  assert.throws(() => loadPhase9RemoteProviderConfig({ OPENAI_API_KEY: "secret", REMOTE_PROVIDER_REQUEST_TIMEOUT_MS: "30000", REMOTE_PROVIDER_MAX_RESPONSE_BYTES: "1048576" }), (error) => error instanceof ConfigurationError && error.key === "OPENAI_BASE_URL");
  const config = loadPhase9RemoteProviderConfig({
    OPENAI_API_KEY: "openai-secret", OPENAI_BASE_URL: "https://api.openai.test/v1",
    GEMINI_API_KEY: "gemini-secret", GEMINI_BASE_URL: "https://gemini.test/v1",
    JIMENG_API_KEY: "jimeng-secret", JIMENG_BASE_URL: "https://ark.test/api/v3",
    REMOTE_PROVIDER_REQUEST_TIMEOUT_MS: "30000", REMOTE_PROVIDER_MAX_RESPONSE_BYTES: "1048576",
  });
  assert.deepEqual(Object.keys(config).sort(), ["gemini", "jimeng", "openai"]);
});

test("OpenAI adapter sends a provider-local request and returns validated Base64 output", async () => {
  let body: Record<string, unknown> = {};
  const provider = new OpenAIImageProvider(httpConfig("openai"), async (input, init) => {
    assert.equal(String(input), "https://provider.test/v1/images/generations");
    assert.equal(new Headers(init?.headers).get("authorization"), "Bearer test-secret");
    body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return Response.json({ data: [{ b64_json: PNG }] }, { headers: { "x-request-id": "openai-request-1" } });
  });
  const result = await provider.generate(request, binding("openai", "gpt-image-2-2026-04-21", { quality: "medium" }), context);
  assert.equal(result.externalRequestId, "openai-request-1");
  assert.equal(result.outputs[0]?.kind, "base64");
  assert.equal(body.model, "gpt-image-2-2026-04-21");
  assert.equal(body.size, "1024x1024");
  assert.equal(body.n, 1);
  assert.match(String(body.prompt), /Avoid: blur/);
  assert.equal(JSON.stringify(body).includes("test-secret"), false);
});

test("OpenAI moderation blocks are non-retryable and never fall through as transient failures", async () => {
  const provider = new OpenAIImageProvider(httpConfig("openai"), async () => Response.json({ error: { type: "image_generation_user_error", code: "moderation_blocked" } }, { status: 400 }));
  await assert.rejects(provider.generate(request, binding("openai", "gpt-image-2-2026-04-21"), context), (error) => error instanceof ProviderError && error.category === "content_policy" && !error.retryable);
});

test("Gemini adapter maps dimensions to official aspect/size fields and handles safety blocks", async () => {
  let body: Record<string, unknown> = {};
  const provider = new GeminiImageProvider(httpConfig("gemini"), async (input, init) => {
    assert.equal(String(input), "https://provider.test/v1/models/gemini-3.1-flash-image:generateContent");
    assert.equal(new Headers(init?.headers).get("x-goog-api-key"), "test-secret");
    body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return Response.json({ candidates: [{ content: { parts: [{ inlineData: { mimeType: "image/png", data: PNG } }] } }] });
  });
  const result = await provider.generate(request, binding("gemini", "gemini-3.1-flash-image"), context);
  assert.equal(result.outputs.length, 1);
  const generationConfig = body.generationConfig as { responseModalities: string[]; responseFormat: { image: { aspectRatio: string; imageSize: string } } };
  assert.deepEqual(generationConfig.responseModalities, ["IMAGE"]);
  assert.deepEqual(generationConfig.responseFormat.image, { aspectRatio: "1:1", imageSize: "1K" });

  const blocked = new GeminiImageProvider(httpConfig("gemini"), async () => Response.json({ promptFeedback: { blockReason: "SAFETY" } }));
  await assert.rejects(blocked.generate(request, binding("gemini", "gemini-3.1-flash-image"), context), (error) => error instanceof ProviderError && error.category === "content_policy");
});

test("Jimeng adapter uses Seedream synchronous Base64 mode with seed and bounded controls", async () => {
  let body: Record<string, unknown> = {};
  const provider = new JimengImageProvider(httpConfig("jimeng"), async (input, init) => {
    assert.equal(String(input), "https://provider.test/v1/images/generations");
    body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return Response.json({ model: "doubao-seedream-4-5-251128", data: [{ b64_json: PNG, size: "1024x1024" }] }, { headers: { "x-tt-logid": "jimeng-request-1" } });
  });
  const result = await provider.generate({ ...request, seed: 42 }, binding("jimeng", "doubao-seedream-4-5-251128", { watermark: false, guidanceScale: 2.5 }), context);
  assert.equal(result.externalRequestId, "jimeng-request-1");
  assert.equal(body.response_format, "b64_json");
  assert.equal(body.sequential_image_generation, "disabled");
  assert.equal(body.seed, 42);
  assert.equal(body.watermark, false);
});

test("Jimeng adapter fans out count>1 into one API call per image with distinct seeds", async () => {
  const calls: Record<string, unknown>[] = [];
  const provider = new JimengImageProvider(httpConfig("jimeng"), async (_input, init) => {
    calls.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
    return Response.json({ model: "doubao-seedream-4-5-251128", data: [{ b64_json: PNG, size: "1024x1024" }] }, { headers: { "x-tt-logid": `jimeng-request-${calls.length}` } });
  });
  const result = await provider.generate({ ...request, count: 3, seed: 42 }, binding("jimeng", "doubao-seedream-4-5-251128"), context);
  assert.equal(calls.length, 3);
  assert.deepEqual(calls.map((call) => call.seed), [42, 43, 44]);
  assert.equal(result.outputs.length, 3);
  assert.equal(result.externalRequestId, "jimeng-request-3");
});

test("database routing state overrides static adapter priority and disabled providers are excluded", () => {
  const registry = new ProviderRegistry();
  registry.register(new MockImageProvider({ code: "first", priority: 1 }));
  registry.register(new MockImageProvider({ code: "second", priority: 100 }));
  registry.setRouting("first", { availability: "disabled", priority: 1 });
  registry.setRouting("second", { availability: "active", priority: 2 });
  const ranked = new ProviderSelectionPolicy(registry).rank(request, [binding("first"), binding("second")]);
  assert.deepEqual(ranked.map((candidate) => candidate.provider.descriptor.code), ["second"]);
});

test("multi-provider executor retries and falls back only for safe provider failures", async () => {
  const registry = new ProviderRegistry();
  registry.register(new MockImageProvider({ code: "primary", priority: 1, failure: new ProviderError({ providerCode: "primary", category: "unavailable", code: "upstream_503", message: "Unavailable" }) }));
  registry.register(new MockImageProvider({ code: "secondary", priority: 2 }));
  const calls: string[] = [];
  const pipeline = { async execute(provider: MockImageProvider) { calls.push(provider.descriptor.code); await provider.generate(request, binding(provider.descriptor.code), context); return productionResult(provider.descriptor.code); } };
  const executor = new MultiProviderExecutor(new ProviderSelectionPolicy(registry), pipeline, silentLogger(), { retryBaseMs: 0, maxTotalCalls: 5 });
  const result = await executor.execute(request, [binding("primary", undefined, {}, { maxAttempts: 2, priority: 1 }), binding("secondary", undefined, {}, { priority: 2 })], context);
  assert.equal(result.providerCode, "secondary");
  assert.deepEqual(calls, ["primary", "primary", "secondary"]);
});

test("content policy failures stop before another provider can be called", async () => {
  const registry = new ProviderRegistry();
  registry.register(new MockImageProvider({ code: "primary", priority: 1, failure: new ProviderError({ providerCode: "primary", category: "content_policy", code: "blocked", message: "Blocked", retryable: false }) }));
  registry.register(new MockImageProvider({ code: "secondary", priority: 2 }));
  const calls: string[] = [];
  const pipeline = { async execute(provider: MockImageProvider) { calls.push(provider.descriptor.code); await provider.generate(request, binding(provider.descriptor.code), context); return productionResult(provider.descriptor.code); } };
  const executor = new MultiProviderExecutor(new ProviderSelectionPolicy(registry), pipeline, silentLogger());
  await assert.rejects(executor.execute(request, [binding("primary", undefined, {}, { priority: 1 }), binding("secondary", undefined, {}, { priority: 2 })], context), (error) => error instanceof ProviderError && error.category === "content_policy");
  assert.deepEqual(calls, ["primary"]);
});

function httpConfig(providerCode: string) { return { providerCode, baseUrl: "https://provider.test/v1", apiKey: "test-secret", requestTimeoutMs: 30_000, maxResponseBytes: 1_048_576 }; }
function binding(providerCode: string, providerModel?: string, providerConfig: Record<string, string | number | boolean> = {}, overrides: Partial<ProviderBinding> = {}): ProviderBinding { return { id: `binding-${providerCode}`, providerCode, workflowVersionId: request.workflow.workflowVersionId, ...(providerModel ? { providerModel } : {}), providerConfig, priority: 100, estimatedCost: 0.01, timeoutSeconds: 300, maxAttempts: 1, enabled: true, ...overrides }; }
function productionResult(providerCode: string) { return { externalRequestId: `external-${providerCode}`, assets: [], providerCode, providerMetadata: {}, generationDurationMs: 1, storageDurationMs: 1 }; }
function silentLogger() { return { info() { return undefined; }, error() { return undefined; } }; }
