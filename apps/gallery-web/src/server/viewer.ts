import "server-only";

import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import type { ViewerBridge, ViewerContext, ViewerRole } from "@/lib/gallery-types";

export async function resolveViewerFromRequest(): Promise<ViewerContext> {
  return resolveViewerFromCookieHeader((await cookies()).toString());
}

export async function resolveViewerFromCookieHeader(cookieHeader: string): Promise<ViewerContext> {
  const requestId = randomUUID();
  const fallback = (bridge: ViewerBridge): ViewerContext => ({ role: "guest", requestId, bridge });
  const url = process.env.MAVIS_AUTH_INTROSPECTION_URL?.trim();
  const secret = process.env.GALLERY_INTROSPECTION_SECRET?.trim();
  if (!url || !secret || Buffer.byteLength(secret, "utf8") < 32) {
    console.info(
      `[viewer] introspection unconfigured (url=${Boolean(url)}, secretLength=${secret ? Buffer.byteLength(secret, "utf8") : 0})`,
    );
    return fallback("unconfigured");
  }

  let endpoint: URL;
  try { endpoint = new URL(url); } catch { return fallback("unconfigured"); }
  if (endpoint.protocol !== "https:" && !(endpoint.protocol === "http:" && isLoopback(endpoint.hostname))) {
    return fallback("unconfigured");
  }

  try {
    const response = await fetch(endpoint, {
      method: "GET",
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
      headers: {
        Accept: "application/json",
        Cookie: cookieHeader,
        "X-Mavis-Introspection-Secret": secret,
      },
    });
    if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) {
      console.info(
        `[viewer] introspection failed status=${response.status} type=${response.headers.get("content-type") ?? "none"}`,
      );
      return fallback("error");
    }
    const body = await response.json() as unknown;
    if (!body || typeof body !== "object" || Array.isArray(body)) return fallback("error");
    const role = (body as { role?: unknown }).role;
    const userId = (body as { userId?: unknown }).userId;
    if (!isRole(role)) return fallback("error");
    if (role === "guest") return fallback("guest");
    if (!Number.isInteger(userId) || Number(userId) <= 0) return fallback("error");
    console.info(`[viewer] introspection ok role=${role} userId=${Number(userId)}`);
    return { role, userId: Number(userId), requestId, bridge: "ok" };
  } catch (reason) {
    console.info(`[viewer] introspection exception ${String(reason)}`);
    return fallback("error");
  }
}

function isRole(value: unknown): value is ViewerRole { return value === "guest" || value === "user" || value === "admin"; }
function isLoopback(hostname: string): boolean { return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1" || hostname === "[::1]"; }
