import "server-only";

import { checkRateLimit, isSameOrigin, requireViewerRole } from "./bff-security";
import { resolveViewerFromCookieHeader } from "./viewer";
import { safeProxyError, serviceRequest } from "./gallery-client";

export async function proxyGalleryRequest(request: Request, servicePath: string, method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE" = "GET"): Promise<Response> {
  if (method !== "GET") {
    const invalidOrigin = !isSameOrigin(request);
    if (invalidOrigin) return Response.json({ error: { code: "forbidden", message: "禁止跨站操作，请刷新后重试。" } }, { status: 403 });
  }
  const viewer = await resolveViewerFromCookieHeader(request.headers.get("cookie") ?? "");
  const adminGuard = servicePath.startsWith("/v1/admin/") ? requireViewerRole(viewer, "admin") : undefined;
  if (adminGuard) return adminGuard;
  const redeemGuard = servicePath === "/v1/billing/redeem" ? requireViewerRole(viewer, "user") : undefined;
  if (redeemGuard) return redeemGuard;
  // User-scoped and personal data endpoints must require a signed-in user in
  // the BFF as well (defense in depth): /v1/me/*, like/favorite/download
  // mutations, and billing endpoints. The Generation Service enforces its own
  // role checks, but never rely on the downstream as the only gate.
  const userScopedPath = servicePath.startsWith("/v1/me/")
    || servicePath.startsWith("/v1/billing/")
    || /^\/v1\/images\/[^/]+\/(?:like|favorite|download)$/.test(servicePath);
  const userGuard = userScopedPath ? requireViewerRole(viewer, "user") : undefined;
  if (userGuard) return userGuard;
  if (servicePath === "/v1/billing/redeem" && method === "POST") {
    const rateLimit = checkRateLimit(request, viewer, "redeem", 5);
    if (rateLimit) return rateLimit;
  }
  try {
    // Admin / billing / interaction bodies are small; keep a 16KB ceiling but
    // fast-fail on Content-Length before buffering an oversized body.
    const maxBodyBytes = 16 * 1024;
    const declaredLength = Number(request.headers.get("content-length") ?? "0");
    if ((method === "PATCH" || method === "POST" || method === "PUT") && Number.isFinite(declaredLength) && declaredLength > maxBodyBytes) {
      return Response.json({ error: { code: "invalid_request", message: "请求内容过大。" } }, { status: 413 });
    }
    const text = method === "PATCH" || method === "POST" || method === "PUT" ? await request.text() : "";
    if (text.length > maxBodyBytes) return Response.json({ error: { code: "invalid_request", message: "请求内容过大。" } }, { status: 413 });
    const result = await serviceRequest<unknown>(servicePath, viewer, { method, ...(text ? { body: text } : {}) });
    return method === "DELETE" && result === undefined ? new Response(null, { status: 204 }) : Response.json(result);
  } catch (error) {
    return safeProxyError(error);
  }
}
