import assert from "node:assert/strict";
import { access, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { ComfyUIClient, type ComfyRetryEvent } from "../src/comfyui/client.ts";
import { ComfyUIProvider } from "../src/comfyui/provider.ts";
import { ConfigurationError, loadPhase4Config, type ComfyUIConfig, type TencentCosConfig } from "../src/config.ts";
import { ImagePersistenceService } from "../src/pipeline/image-persistence.ts";
import { PollingService } from "../src/pipeline/polling-service.ts";
import { ProductionGenerationPipeline } from "../src/pipeline/production-generation-pipeline.ts";
import { ProviderError } from "../src/providers/errors.ts";
import { MockImageProvider } from "../src/providers/mock.provider.ts";
import type { GenerationRequest, ProviderBinding, ProviderCallContext } from "../src/providers/types.ts";
import { sanitizeMetadataKey, TencentCosStorage } from "../src/storage/tencent-cos.storage.ts";
import { injectPlaceholders, WorkflowPlaceholderError } from "../src/workflows/placeholder-injector.ts";
import { WorkflowLoadError, WorkflowLoader } from "../src/workflows/workflow-loader.ts";

const PNG_1X1 = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
const workflowDirectory = fileURLToPath(new URL("../workflows", import.meta.url));
const request: GenerationRequest = {
  jobId: "job-phase4",
  workflow: { workflowId: "portrait", workflowVersionId: "portrait-v1-id", version: 1, kind: "portrait" },
  mode: "text-to-image",
  prompt: "a studio portrait",
  negativePrompt: "blur",
  width: 1024,
  height: 1024,
  count: 1,
  seed: 42,
  parameters: { steps: 24, cfg: 7, sampler: "euler", scheduler: "normal" },
};
const context: ProviderCallContext = { requestId: "request-phase4", attemptId: "attempt-phase4" };
const binding: ProviderBinding = {
  id: "binding-comfyui",
  providerCode: "comfyui",
  workflowVersionId: request.workflow.workflowVersionId,
  providerWorkflowRef: "portrait-v1",
  providerModel: "sdxl.safetensors",
  providerConfig: {},
  priority: 10,
  estimatedCost: 0.02,
  timeoutSeconds: 300,
  maxAttempts: 2,
  enabled: true,
};

test("placeholder injection preserves exact value types and rejects missing or unknown tokens", () => {
  const result = injectPlaceholders({ seed: "{{seed}}", text: "prefix {{prompt}}" }, { seed: 7, prompt: "hello" });
  assert.deepEqual(result, { seed: 7, text: "prefix hello" });
  assert.throws(() => injectPlaceholders("{{steps}}", {}), (error) => error instanceof WorkflowPlaceholderError && error.reason === "missing");
  assert.throws(() => injectPlaceholders("{{password}}", {}), (error) => error instanceof WorkflowPlaceholderError && error.reason === "unknown");
});

test("workflow loader validates versioned API workflows and blocks unsafe references", async () => {
  const loader = new WorkflowLoader(workflowDirectory);
  const loadedWorkflows = await Promise.all(["portrait-v1", "anime-v1", "food-v1", "architecture-v1"].map((reference) => loader.load(reference)));
  const loaded = loadedWorkflows[0];
  assert.ok(loaded);
  assert.equal(loaded.workflowName, "portrait");
  assert.equal(loaded.workflowVersion, 1);
  assert.equal(loaded.digest.length, 64);
  assert.notEqual((await loader.load("portrait-v1")).template, loaded.template);
  await assert.rejects(loader.load("../portrait-v1"), (error) => error instanceof WorkflowLoadError && error.code === "invalid_reference");
});

test("phase 4 configuration is environment-only and fails closed", () => {
  assert.throws(() => loadPhase4Config({}), ConfigurationError);
  const config = loadPhase4Config({
    COMFYUI_BASE_URL: "http://127.0.0.1:8188/",
    COMFYUI_HEADERS_JSON: "{}",
    COMFYUI_REQUEST_TIMEOUT_MS: "1000",
    COMFYUI_DOWNLOAD_TIMEOUT_MS: "2000",
    COMFYUI_RETRY_COUNT: "2",
    COMFYUI_RETRY_DELAY_MS: "0",
    COMFYUI_POLL_INTERVAL_MS: "100",
    COMFYUI_POLL_MAX_ATTEMPTS: "10",
    COMFYUI_ALLOW_GLOBAL_INTERRUPT: "false",
    COMFYUI_WORKFLOW_DIR: workflowDirectory,
    COMFYUI_DOWNLOAD_DIR: workflowDirectory,
    COS_SECRET_ID: "id",
    COS_SECRET_KEY: "key",
    COS_BUCKET: "bucket-123",
    COS_REGION: "ap-shanghai",
    GENERATION_LOG_PROMPTS: "false",
  });
  assert.equal(config.comfyui.baseUrl, "http://127.0.0.1:8188");
  assert.equal(config.cos.region, "ap-shanghai");
  assert.equal(config.logPrompts, false);
});

test("ComfyUI client retries transient failures and never exposes response bodies", async () => {
  let calls = 0;
  const retries: ComfyRetryEvent[] = [];
  const client = new ComfyUIClient(comfyConfig(workflowDirectory, { retryCount: 1 }), (async () => {
    calls += 1;
    return calls === 1 ? new Response("secret upstream body", { status: 503 }) : Response.json({ prompt_id: "prompt-1" });
  }) as typeof fetch, (event) => retries.push(event));
  assert.equal(await client.queuePrompt({ "1": { class_type: "Test", inputs: {} } }, "client-1"), "prompt-1");
  assert.equal(calls, 2);
  assert.deepEqual(retries.map((event) => event.retryNumber), [1]);

  const unauthorized = new ComfyUIClient(comfyConfig(workflowDirectory), (async () => new Response("token leaked", { status: 401 })) as typeof fetch);
  await assert.rejects(unauthorized.healthCheck(), (error) => error instanceof ProviderError && error.category === "authentication" && !error.message.includes("token leaked"));
});

test("ComfyUI provider, polling and Tencent COS persistence complete end to end", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "phase4-comfy-"));
  const requests: string[] = [];
  const fetcher = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    requests.push(`${init?.method ?? "GET"} ${new URL(url).pathname}`);
    if (url.endsWith("/prompt")) return Response.json({ prompt_id: "prompt-e2e" });
    if (url.includes("/history/prompt-e2e")) return Response.json({ "prompt-e2e": { status: { completed: true, status_str: "success" }, outputs: { "9": { images: [{ filename: "image.png", subfolder: "", type: "output" }] } } } });
    if (url.includes("/view?")) return new Response(PNG_1X1, { status: 200, headers: { "content-type": "image/png" } });
    throw new Error(`Unexpected request ${url}`);
  }) as typeof fetch;
  const uploads: Record<string, unknown>[] = [];
  const deletes: string[] = [];
  const cosClient = {
    putObject(options: Record<string, unknown>, callback: (error: Error | null, data?: { ETag?: string }) => void): void { uploads.push(options); callback(null, { ETag: "etag-1" }); },
    deleteObject(options: Record<string, unknown>, callback: (error: Error | null) => void): void { deletes.push(String(options.Key)); callback(null); },
  };
  const cos = new TencentCosStorage(cosConfig(), cosClient);
  const provider = new ComfyUIProvider(new ComfyUIClient(comfyConfig(root), fetcher), new WorkflowLoader(workflowDirectory));
  const logs: Array<{ level: string; event: string; fields: Record<string, unknown> }> = [];
  const logger = {
    info(event: string, fields: Record<string, unknown>): void { logs.push({ level: "info", event, fields }); },
    error(event: string, fields: Record<string, unknown>): void { logs.push({ level: "error", event, fields }); },
  };
  const pipeline = new ProductionGenerationPipeline(new PollingService({ intervalMs: 1, maxAttempts: 2 }, async () => undefined), new ImagePersistenceService(cos, root, 1000, fetcher), logger);
  try {
    const result = await pipeline.execute(provider, request, binding, context);
    assert.equal(result.assets.length, 1);
    assert.equal(result.assets[0]?.objectKey, "images/jobs/job-phase4/0.png");
    assert.match(result.assets[0]?.url ?? "", /^https:\/\/bucket-123\.cos\.ap-shanghai\.myqcloud\.com\/images\//);
    assert.equal(result.providerMetadata.outputCount, 1);
    assert.equal(uploads.length, 1);
    assert.equal(deletes.length, 0);
    const headers = uploads[0]?.Headers as Record<string, unknown> | undefined;
    assert.equal(headers?.["x-cos-meta-job-id"], "job-phase4");
    assert.equal(headers?.["x-cos-meta-output-index"], "0");
    assert.equal("x-cos-meta-job_id" in (headers ?? {}), false);
    assert.deepEqual(requests, ["POST /prompt", "GET /history/prompt-e2e", "GET /view"]);
    assert.equal(logs.some((entry) => entry.event === "generation.completed" && !("prompt" in entry.fields)), true);
    await assert.rejects(access(path.join(root, "attempt-phase4-0.png")));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("COS metadata header names are normalized to hyphenated lowercase keys", () => {
  assert.equal(sanitizeMetadataKey("job_id"), "job-id");
  assert.equal(sanitizeMetadataKey("output_index"), "output-index");
  assert.equal(sanitizeMetadataKey("Job ID"), "job-id");
  assert.equal(sanitizeMetadataKey("___"), "meta");
});

test("queued cancellation uses targeted queue deletion and leaves global interrupt disabled", async () => {
  const bodies: string[] = [];
  const fetcher = (async (_input: string | URL | Request, init?: RequestInit) => { bodies.push(String(init?.body)); return Response.json({}); }) as typeof fetch;
  const client = new ComfyUIClient(comfyConfig(workflowDirectory), fetcher);
  assert.equal(await client.cancelPrompt("prompt-7"), true);
  assert.deepEqual(bodies, [JSON.stringify({ delete: ["prompt-7"] })]);
});

test("polling exhaustion maps to a retryable timeout", async () => {
  const provider = new MockImageProvider({ asynchronous: true, latencyMs: 60_000 });
  const submission = await provider.generate(request, { ...binding, providerCode: "mock" }, context);
  const polling = new PollingService({ intervalMs: 1, maxAttempts: 2 }, async () => undefined);
  await assert.rejects(polling.wait(provider, submission, context), (error) => error instanceof ProviderError && error.code === "polling_exhausted" && error.retryable);
});

test("persistence compensates earlier COS uploads and removes temporary files after failure", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "phase4-cleanup-"));
  const first = path.join(root, "first.png");
  const second = path.join(root, "second.png");
  await writeFile(first, PNG_1X1);
  await writeFile(second, PNG_1X1);
  const deleted: string[] = [];
  let count = 0;
  const storage = {
    code: "test",
    async upload(input: { objectKey: string }) { count += 1; if (count === 2) throw new Error("upload failed"); return { storageProvider: "test", bucket: "b", region: "r", objectKey: input.objectKey, url: "https://example.test/object" }; },
    async delete(objectKey: string) { deleted.push(objectKey); },
  };
  try {
    const service = new ImagePersistenceService(storage, root, 1000);
    await assert.rejects(service.persist("job-cleanup", [
      { kind: "local-file", path: first, mimeType: "image/png", width: 1, height: 1 },
      { kind: "local-file", path: second, mimeType: "image/png", width: 1, height: 1 },
    ]), /upload failed/);
    assert.equal(deleted.length, 1);
    await assert.rejects(readFile(first));
    await assert.rejects(readFile(second));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

function comfyConfig(downloadDirectory: string, overrides: Partial<ComfyUIConfig> = {}): ComfyUIConfig {
  return { baseUrl: "http://comfy.internal:8188", headers: {}, requestTimeoutMs: 1000, downloadTimeoutMs: 1000, retryCount: 0, retryDelayMs: 0, pollIntervalMs: 10, pollMaxAttempts: 5, allowGlobalInterrupt: false, workflowDirectory, downloadDirectory, ...overrides };
}

function cosConfig(): TencentCosConfig {
  return { secretId: "secret-id", secretKey: "secret-key", bucket: "bucket-123", region: "ap-shanghai" };
}
