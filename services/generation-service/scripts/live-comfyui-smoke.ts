/**
 * Live ComfyUI video smoke test through the signed internal Generation API.
 *
 * Requires a running stack (Generation API, Dispatcher, Worker, PostgreSQL,
 * Redis, COS and ComfyUI configured in .env) and a user with credits.
 * Creates one real 5-second private video job and polls it to a terminal
 * state. Never prints the HMAC secret or the full prompt.
 *
 * Run from services/generation-service:
 *
 *   $env:SMOKE_USER_ID = "3"
 *   npm run smoke:comfyui
 *
 * Against a remote Staging API:
 *
 *   $env:SMOKE_API_BASE_URL = "https://api-ai-staging.example.com"
 *   npm run smoke:comfyui
 */
import { createHmac, randomUUID } from "node:crypto";

const baseUrl = (process.env.SMOKE_API_BASE_URL ?? "http://127.0.0.1:3101").replace(/\/+$/, "");
const secret = process.env.GALLERY_INTERNAL_HMAC_SECRET?.trim();
const userId = Number(process.env.SMOKE_USER_ID?.trim() ?? "");

function requiredSecret(): string {
  if (!secret) throw new Error("GALLERY_INTERNAL_HMAC_SECRET is not configured");
  return secret;
}

function sign(targetUserId: number, requestId: string): Record<string, string> {
  const now = Math.floor(Date.now() / 1000);
  const payload = { v: 1, role: "user", userId: targetUserId, requestId, issuedAt: now, expiresAt: now + 120 };
  const context = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature = createHmac("sha256", requiredSecret()).update(context).digest("base64url");
  return { "x-mavis-user-context": context, "x-mavis-user-signature": signature };
}

async function main(): Promise<void> {
  if (process.argv[2] === "--health") {
    const response = await fetch(`${baseUrl}/health`);
    console.log(`[${response.ok ? "PASS" : "FAIL"}] generation api health: ${response.status}`);
    process.exit(response.ok ? 0 : 1);
  }

  if (!Number.isInteger(userId) || userId <= 0) throw new Error("SMOKE_USER_ID must be a positive integer");
  const workflowSlug = process.env.SMOKE_WORKFLOW_SLUG?.trim() ?? "comfyui-ltx-video-v1";
  const durationSeconds = Number(process.env.SMOKE_DURATION_SECONDS?.trim() ?? "5");
  const width = Number(process.env.SMOKE_WIDTH?.trim() ?? "960");
  const height = Number(process.env.SMOKE_HEIGHT?.trim() ?? "544");
  const creditTier = process.env.SMOKE_CREDIT_TIER?.trim() ?? "free";
  const timeoutMs = Number(process.env.SMOKE_TIMEOUT_MS?.trim() ?? "720000");
  const prompt = process.env.SMOKE_PROMPT?.trim() ?? "夕阳下的海边，海浪缓缓推进，云层被染成金红色，镜头缓慢向前";
  const negativePrompt = process.env.SMOKE_NEGATIVE_PROMPT?.trim() ?? "水印, 文字, 低质量";

  const createResponse = await fetch(`${baseUrl}/v1/generations`, {
    method: "POST",
    headers: { "content-type": "application/json", "idempotency-key": randomUUID(), ...sign(userId, randomUUID()) },
    body: JSON.stringify({
      workflowSlug,
      prompt,
      negativePrompt,
      width,
      height,
      count: 1,
      visibility: "private",
      promptVisibility: "hidden",
      creditTier,
      parameters: { durationSeconds },
    }),
  });
  const created = (await createResponse.json()) as {
    id?: string;
    status?: string;
    creditsReserved?: string;
    error?: { code?: string; message?: string };
  };
  if (createResponse.status !== 202 || !created.id) {
    console.error(
      `[FAIL] create: HTTP ${createResponse.status} code=${created.error?.code ?? "?"} message=${created.error?.message ?? JSON.stringify(created)}`,
    );
    process.exit(1);
  }
  console.log(`[OK] created job=${created.id} status=${created.status ?? "?"} reserved=${created.creditsReserved ?? "?"}`);

  const deadline = Date.now() + timeoutMs;
  let last = "";
  while (Date.now() < deadline) {
    const response = await fetch(`${baseUrl}/v1/generations/${created.id}`, { headers: sign(userId, randomUUID()) });
    const view = (await response.json()) as {
      status?: string;
      outputs?: readonly { url?: string; mimeType?: string; width?: number; height?: number; durationSeconds?: number }[];
      creditsCharged?: string;
      error?: { code?: string; message?: string };
    };
    const status = view.status ?? "unknown";
    if (status !== last) {
      last = status;
      console.log(`[..] status=${status}`);
    }
    if (status === "completed") {
      const output = view.outputs?.[0];
      console.log(
        `[PASS] completed charged=${view.creditsCharged ?? "?"} url=${output?.url ?? "?"} mime=${output?.mimeType ?? "?"} size=${output?.width ?? "?"}x${output?.height ?? "?"} duration=${output?.durationSeconds ?? "?"}s`,
      );
      process.exit(0);
    }
    if (status === "failed" || status === "cancelled") {
      console.error(`[FAIL] ${status} code=${view.error?.code ?? "?"} message=${view.error?.message ?? "?"}`);
      process.exit(2);
    }
    await new Promise((resolve) => setTimeout(resolve, 8000));
  }
  console.error(`[FAIL] poll timeout after ${timeoutMs}ms`);
  process.exit(3);
}

main().catch((error: unknown) => {
  console.error(`[FAIL] comfyui smoke: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
