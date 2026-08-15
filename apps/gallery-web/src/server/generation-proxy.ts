import "server-only";

import { checkRateLimit, isSameOrigin, requireViewerRole } from "./bff-security";
import { resolveViewerFromCookieHeader } from "./viewer";
import { safeProxyError, serviceRequest } from "./gallery-client";

export async function proxyGenerationRequest(request: Request, servicePath: string, method: "GET" | "POST" | "DELETE"): Promise<Response> {
  if (method !== "GET" && !isSameOrigin(request)) return Response.json({ error: { code: "forbidden", message: "禁止跨站操作，请刷新后重试。" } }, { status: 403 });
  const viewer = await resolveViewerFromCookieHeader(request.headers.get("cookie") ?? "");
  // Both creation (POST) and cancellation/deletion (DELETE) mutate the user's
  // generation tasks; require a signed-in user in the BFF as defense in depth
  // (the Generation Service additionally enforces ownership per job).
  if (method !== "GET") {
    const access = requireViewerRole(viewer, "user");
    if (access) return access;
  }
  if (method === "POST") {
    const rateLimit = checkRateLimit(request, viewer, "generation-create", 10);
    if (rateLimit) return rateLimit;
  }
  try {
    // Generation requests carry base64 reference images (reference-image
    // workflows, H3 video etc.), which routinely exceed 16KB. The Generation
    // Service itself allows a 6MB body (http-server.ts bodyLimit), so mirror
    // that here; a smaller ceiling would make reference-image generation
    // impossible. Fast-fail on an oversized Content-Length before buffering.
    const maxBodyBytes = 6 * 1024 * 1024;
    const declaredLength = Number(request.headers.get("content-length") ?? "0");
    if (method === "POST" && Number.isFinite(declaredLength) && declaredLength > maxBodyBytes) {
      return Response.json({ error: { code: "invalid_request", message: "请求内容过大。" } }, { status: 413 });
    }
    const text = method === "POST" ? await request.text() : "";
    if (text.length > maxBodyBytes) return Response.json({ error: { code: "invalid_request", message: "请求内容过大。" } }, { status: 413 });
    const idempotencyKey = request.headers.get("idempotency-key")?.trim();
    if (idempotencyKey && !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(idempotencyKey)) return Response.json({ error: { code: "invalid_request", message: "请求标识无效，请刷新后重试。" } }, { status: 400 });
    const result = await serviceRequest<unknown>(servicePath, viewer, {
      method,
      ...(text ? { body: text } : {}),
      ...(idempotencyKey ? { headers: { "Idempotency-Key": idempotencyKey } } : {}),
    });
    return Response.json(result, { status: method === "POST" ? 202 : 200 });
  } catch (error) { return safeProxyError(error); }
}
