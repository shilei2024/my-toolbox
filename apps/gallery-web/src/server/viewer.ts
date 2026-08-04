import "server-only";

import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import type { ViewerContext, ViewerRole } from "@/lib/gallery-types";

export async function resolveViewerFromRequest(): Promise<ViewerContext> {
  return resolveViewerFromCookieHeader((await cookies()).toString());
}

export async function resolveViewerFromCookieHeader(cookieHeader: string): Promise<ViewerContext> {
  const fallback: ViewerContext = { role: "guest", requestId: randomUUID() };
  const url = process.env.MAVIS_AUTH_INTROSPECTION_URL?.trim();
  const secret = process.env.GALLERY_INTROSPECTION_SECRET?.trim();
  if (!url || !secret || Buffer.byteLength(secret, "utf8") < 32) return fallback;

  let endpoint: URL;
  try { endpoint = new URL(url); } catch { return fallback; }
  if (endpoint.protocol !== "https:" && !(endpoint.protocol === "http:" && isLoopback(endpoint.hostname))) return fallback;

  try {
    const response = await fetch(endpoint, {
      method: "GET",
      cache: "no-store",
      signal: AbortSignal.timeout(3_000),
      headers: {
        Accept: "application/json",
        Cookie: cookieHeader,
        "X-Mavis-Introspection-Secret": secret,
      },
    });
    if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) return fallback;
    const body = await response.json() as unknown;
    if (!body || typeof body !== "object" || Array.isArray(body)) return fallback;
    const role = (body as { role?: unknown }).role;
    const userId = (body as { userId?: unknown }).userId;
    if (!isRole(role)) return fallback;
    if (role === "guest") return fallback;
    if (!Number.isInteger(userId) || Number(userId) <= 0) return fallback;
    return { role, userId: Number(userId), requestId: fallback.requestId };
  } catch {
    return fallback;
  }
}

function isRole(value: unknown): value is ViewerRole { return value === "guest" || value === "user" || value === "admin"; }
function isLoopback(hostname: string): boolean { return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1" || hostname === "[::1]"; }
