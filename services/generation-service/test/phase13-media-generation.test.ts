import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { Readable } from "node:stream";
import test from "node:test";
import { VideoPersistenceService } from "../src/pipeline/media-persistence.ts";
import type { GenerationRequest, ProviderBinding, ProviderCallContext } from "../src/providers/types.ts";
import { ArkVideoProvider } from "../src/remote-providers/ark-video.ts";
import type { StorageProvider, StorageUpload } from "../src/storage/storage-provider.ts";

const context: ProviderCallContext = { requestId: "request-media", attemptId: "attempt-media" };
const request: GenerationRequest = {
  jobId: "job-media-1",
  workflow: { workflowId: "video", workflowVersionId: "video-v1", version: 1, kind: "AI 视频" },
  mediaType: "video",
  mode: "text-to-video",
  prompt: "雨夜城市中缓慢推进的镜头",
  negativePrompt: "水印",
  width: 1280,
  height: 720,
  count: 1,
  parameters: { durationSeconds: 5 },
  creditTier: "member",
};
const binding: ProviderBinding = {
  id: "binding-video",
  providerCode: "ark-video",
  workflowVersionId: "video-v1",
  providerModel: "doubao-seedance-2-0-260128",
  modelTier: "member",
  providerConfig: { resolution: "720p", watermark: false, generateAudio: false },
  priority: 10,
  timeoutSeconds: 1800,
  maxAttempts: 1,
  enabled: true,
};

test("Ark video adapter submits, polls and normalizes an HTTPS MP4 output", async () => {
  const calls: Array<{ method: string; url: string; body?: Record<string, unknown> }> = [];
  const provider = new ArkVideoProvider({ providerCode: "ark-video", baseUrl: "https://ark.test/api/v3", apiKey: "ark-secret", requestTimeoutMs: 30_000, maxResponseBytes: 1_048_576 }, async (input, init) => {
    const method = init?.method ?? "GET";
    const item = { method, url: String(input), ...(init?.body ? { body: JSON.parse(String(init.body)) as Record<string, unknown> } : {}) };
    calls.push(item);
    if (method === "POST") return Response.json({ id: "cgt-media-1" }, { headers: { "x-request-id": "ark-request-1" } });
    return Response.json({ id: "cgt-media-1", status: "succeeded", duration: 5, content: { video_url: "https://output.test/video.mp4?token=temporary" } });
  });

  const submission = await provider.generate(request, binding, context);
  assert.equal(submission.state, "queued");
  assert.equal(submission.externalRequestId, "cgt-media-1");
  const created = calls[0]!.body!;
  assert.equal(created.model, binding.providerModel);
  assert.equal(created.ratio, "16:9");
  assert.equal(created.duration, 5);
  assert.equal(JSON.stringify(created).includes("ark-secret"), false);

  const status = await provider.getStatus(submission.externalRequestId, context);
  assert.equal(status.state, "succeeded");
  assert.deepEqual(status.outputs, [{ mediaType: "video", kind: "remote-url", url: "https://output.test/video.mp4?token=temporary", mimeType: "video/mp4", width: 1280, height: 720, durationSeconds: 5 }]);
  assert.equal(calls[1]!.url, "https://ark.test/api/v3/contents/generations/tasks/cgt-media-1");
});

test("Ark video adapter maps queued cancellation without exposing credentials", async () => {
  const methods: string[] = [];
  const provider = new ArkVideoProvider({ providerCode: "ark-video", baseUrl: "https://ark.test/api/v3", apiKey: "ark-secret", requestTimeoutMs: 30_000, maxResponseBytes: 1_048_576 }, async (_input, init) => {
    methods.push(init?.method ?? "GET");
    return (init?.method ?? "GET") === "POST" ? Response.json({ id: "cgt-cancel-1" }) : Response.json({});
  });
  const submission = await provider.generate(request, binding, context);
  assert.deepEqual(await provider.cancel(submission.externalRequestId, context), { externalRequestId: "cgt-cancel-1", accepted: true, state: "cancelled" });
  assert.deepEqual(methods, ["POST", "DELETE"]);
});

test("video persistence streams bounded output into the durable storage namespace", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "mavis-video-test-"));
  const uploads: StorageUpload[] = [];
  const storage: StorageProvider = {
    code: "test-storage",
    async upload(input) {
      uploads.push(input);
      if (input.body instanceof Readable) for await (const _chunk of input.body) { /* drain */ }
      return { storageProvider: "test-storage", bucket: "bucket", region: "region", objectKey: input.objectKey, url: `https://cdn.test/${input.objectKey}` };
    },
    async download() { return Buffer.alloc(0); },
    async delete() {},
  };
  try {
    const persistence = new VideoPersistenceService(storage, root, 5_000, 1024, async () => new Response(Buffer.alloc(64, 1), { headers: { "content-length": "64", "content-type": "video/mp4" } }));
    const assets = await persistence.persist("job-video-1", [{ mediaType: "video", kind: "remote-url", url: "https://provider.test/result.mp4", mimeType: "video/mp4", width: 1280, height: 720, durationSeconds: 5 }], "owner-7");
    assert.equal(assets[0]?.objectKey, "videos/owner-7/job-video-1/0.mp4");
    assert.equal(assets[0]?.byteSize, 64);
    assert.equal(assets[0]?.sha256.length, 64);
    assert.equal(uploads.length, 1);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("video persistence rejects declared oversized downloads before uploading", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "mavis-video-limit-test-"));
  let uploaded = false;
  const storage: StorageProvider = { code: "test-storage", async upload() { uploaded = true; throw new Error("must not upload"); }, async download() { return Buffer.alloc(0); }, async delete() {} };
  try {
    const persistence = new VideoPersistenceService(storage, root, 5_000, 32, async () => new Response(Buffer.alloc(1), { headers: { "content-length": "33" } }));
    await assert.rejects(persistence.persist("job-video-2", [{ mediaType: "video", kind: "remote-url", url: "https://provider.test/result.mp4", mimeType: "video/mp4", width: 720, height: 1280, durationSeconds: 5 }]), /size limit/);
    assert.equal(uploaded, false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
