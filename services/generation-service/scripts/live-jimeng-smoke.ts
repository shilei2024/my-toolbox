/**
 * Live 即梦 / Seedream smoke test.
 *
 * Uses the real Jimeng adapter against the configured Ark endpoint. Requires
 * JIMENG_API_KEY (and optional JIMENG_BASE_URL / JIMENG_MODEL). Never prints
 * the API key. Run from services/generation-service:
 *
 *   npm run smoke:jimeng
 *   npm run smoke:jimeng -- --health
 *   npm run smoke:jimeng -- "一只安静的橘猫坐在窗台上"
 */
import { mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { GenerationRequest, ProviderBinding, ProviderCallContext } from "../src/providers/types.ts";
import { JimengImageProvider } from "../src/remote-providers/jimeng.ts";

function envValue(name: string): string | undefined {
  return process.env[name]?.trim() || undefined;
}

function endpointConfig() {
  const apiKey = envValue("JIMENG_API_KEY");
  if (!apiKey) {
    console.error("[FAIL] JIMENG_API_KEY is not configured. Add it to the environment and retry.");
    process.exit(1);
  }
  return {
    apiKey,
    baseUrl: envValue("JIMENG_BASE_URL") ?? "https://ark.cn-beijing.volces.com/api/v3",
    requestTimeoutMs: Number(envValue("REMOTE_PROVIDER_REQUEST_TIMEOUT_MS") ?? "60000"),
    maxResponseBytes: Number(envValue("REMOTE_PROVIDER_MAX_RESPONSE_BYTES") ?? "20971520"),
  };
}

async function main(): Promise<void> {
  const mode = process.argv[2] ?? "generate";
  const { apiKey, baseUrl, requestTimeoutMs, maxResponseBytes } = endpointConfig();
  const provider = new JimengImageProvider({
    providerCode: "jimeng",
    baseUrl,
    apiKey,
    requestTimeoutMs,
    maxResponseBytes,
  });
  const requestId = `live-${Date.now()}`;
  const context: ProviderCallContext = { requestId, attemptId: `live-attempt-${Date.now()}` };

  if (mode === "--health") {
    const health = await provider.healthCheck(context);
    const message = health.message ?? `latency ${health.latencyMs}ms`;
    console.log(`[${health.healthy ? "PASS" : "FAIL"}] jimeng health: ${message}`);
    process.exit(health.healthy ? 0 : 1);
  }

  const prompt = mode === "generate" ? "一只安静的橘猫坐在窗台上，柔和晨光，写实摄影" : mode;
  const request: GenerationRequest = {
    jobId: requestId,
    workflow: { workflowId: "portrait", workflowVersionId: "live-version", version: 1, kind: "portrait" },
    mode: "text-to-image",
    prompt,
    negativePrompt: "模糊、文字、水印",
    width: 1024,
    height: 1024,
    count: 1,
    parameters: {},
  };
  const binding: ProviderBinding = {
    id: "live-binding",
    providerCode: "jimeng",
    workflowVersionId: request.workflow.workflowVersionId,
    providerModel: envValue("JIMENG_MODEL") ?? "doubao-seedream-4-5-251128",
    providerConfig: { watermark: true },
    priority: 1,
    estimatedCost: 1,
    timeoutSeconds: 300,
    maxAttempts: 1,
    enabled: true,
  };

  const started = Date.now();
  const result = await provider.generate(request, binding, context);
  const output = result.outputs[0];
  if (!output) throw new Error("Jimeng returned no output");
  const extension = output.mimeType === "image/png" ? "png" : output.mimeType === "image/jpeg" ? "jpg" : "webp";
  const outDir = path.join(os.tmpdir(), "mavis-jimeng-smoke");
  await mkdir(outDir, { recursive: true });
  const target = path.join(outDir, `jimeng-${Date.now()}.${extension}`);
  await writeFile(target, Buffer.from(output.data, "base64"));
  const model = (result.providerMetadata as { model?: string }).model ?? "unknown";
  console.log(`[PASS] jimeng generate: model=${model} size=${output.width}x${output.height} mime=${output.mimeType} bytes=${output.data.length} elapsed=${Date.now() - started}ms externalRequestId=${result.externalRequestId}`);
  console.log(`saved=${target}`);
}

main().catch((error: unknown) => {
  console.error(`[FAIL] jimeng smoke: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
