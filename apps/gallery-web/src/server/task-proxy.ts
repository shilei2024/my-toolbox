import "server-only";

import { requireViewerRole } from "./bff-security";
import { safeProxyError, serviceRequest } from "./gallery-client";
import { resolveViewerFromCookieHeader } from "./viewer";

export async function proxyTaskRequest(request: Request): Promise<Response> {
  const viewer = await resolveViewerFromCookieHeader(request.headers.get("cookie") ?? "");
  const access = requireViewerRole(viewer, "user");
  if (access) return access;
  try {
    return Response.json(await serviceRequest<unknown>(`/v1/tasks${new URL(request.url).search}`, viewer));
  } catch (error) {
    return safeProxyError(error);
  }
}
