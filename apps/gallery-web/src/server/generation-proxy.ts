import "server-only";

import { resolveViewerFromCookieHeader } from "./viewer";
import { safeProxyError, serviceRequest } from "./gallery-client";

export async function proxyGenerationRequest(request: Request, servicePath: string, method: "GET" | "POST" | "DELETE"): Promise<Response> {
  if (method !== "GET" && !sameOrigin(request)) return Response.json({ error: { code: "forbidden", message: "Cross-site mutation is not allowed" } }, { status: 403 });
  const viewer = await resolveViewerFromCookieHeader(request.headers.get("cookie") ?? "");
  try {
    const text = method === "POST" ? await request.text() : "";
    if (text.length > 16 * 1024) return Response.json({ error: { code: "invalid_request", message: "Request body is too large" } }, { status: 413 });
    const idempotencyKey = request.headers.get("idempotency-key")?.trim();
    if (idempotencyKey && !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(idempotencyKey)) return Response.json({ error: { code: "invalid_request", message: "Idempotency key is invalid" } }, { status: 400 });
    const result = await serviceRequest<unknown>(servicePath, viewer, {
      method,
      ...(text ? { body: text } : {}),
      ...(idempotencyKey ? { headers: { "Idempotency-Key": idempotencyKey } } : {}),
    });
    return Response.json(result, { status: method === "POST" ? 202 : 200 });
  } catch (error) { return safeProxyError(error); }
}

function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return request.headers.get("sec-fetch-site") !== "cross-site";
  const configured = process.env.GALLERY_PUBLIC_ORIGIN?.trim();
  const expected = configured || new URL(request.url).origin;
  try { return new URL(origin).origin === new URL(expected).origin; } catch { return false; }
}
