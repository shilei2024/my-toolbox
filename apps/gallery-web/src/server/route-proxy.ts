import "server-only";

import { resolveViewerFromCookieHeader } from "./viewer";
import { safeProxyError, serviceRequest } from "./gallery-client";

export async function proxyGalleryRequest(request: Request, servicePath: string, method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE" = "GET"): Promise<Response> {
  if (method !== "GET") {
    const invalidOrigin = !sameOrigin(request);
    if (invalidOrigin) return Response.json({ error: { code: "forbidden", message: "Cross-site mutation is not allowed" } }, { status: 403 });
  }
  const viewer = await resolveViewerFromCookieHeader(request.headers.get("cookie") ?? "");
  try {
    const text = method === "PATCH" || method === "POST" || method === "PUT" ? await request.text() : "";
    if (text.length > 16 * 1024) return Response.json({ error: { code: "invalid_request", message: "Request body is too large" } }, { status: 413 });
    const result = await serviceRequest<unknown>(servicePath, viewer, { method, ...(text ? { body: text } : {}) });
    return method === "DELETE" && result === undefined ? new Response(null, { status: 204 }) : Response.json(result);
  } catch (error) {
    return safeProxyError(error);
  }
}

function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return request.headers.get("sec-fetch-site") !== "cross-site";
  const configured = process.env.GALLERY_PUBLIC_ORIGIN?.trim();
  const expected = configured || new URL(request.url).origin;
  try { return new URL(origin).origin === new URL(expected).origin; } catch { return false; }
}
