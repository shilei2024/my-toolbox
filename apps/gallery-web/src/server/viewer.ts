import "server-only";

import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import { cache } from "react";
import type { ViewerBridge, ViewerContext, ViewerRole } from "@/lib/gallery-types";
import { hasNamedCookie } from "./cookie-utils";

export const resolveViewerFromRequest = cache(async (): Promise<ViewerContext> => {
  return resolveViewerFromCookieHeader((await cookies()).toString());
});

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
  const sessionCookieName = process.env.MAVIS_AUTH_SESSION_COOKIE_NAME?.trim() || "mytoolbox_session";
  // Most anonymous requests have no Flask session at all. Avoid a cross-service
  // round trip (and its 10-second timeout budget) when the browser cannot
  // possibly authenticate, while retaining full introspection for any session.
  if (!hasNamedCookie(cookieHeader, sessionCookieName)) return fallback("guest");

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
    const emailValue = (body as { email?: unknown }).email;
    const nicknameValue = (body as { nickname?: unknown }).nickname;
    if (!isRole(role)) return fallback("error");
    if (role === "guest") return fallback("guest");
    if (!Number.isInteger(userId) || Number(userId) <= 0) return fallback("error");
    const email = typeof emailValue === "string" && emailValue.trim() ? emailValue.trim().slice(0, 255) : undefined;
    const nickname = typeof nicknameValue === "string" && nicknameValue.trim() ? nicknameValue.trim().slice(0, 80) : undefined;
    const authEpoch = (body as {authEpoch?: unknown}).authEpoch;
    const sessionRef = (body as {sessionRef?: unknown}).sessionRef;
    const auth = Number.isInteger(authEpoch) && Number(authEpoch) >= 0 && typeof sessionRef === "string" && /^[a-f0-9]{64}$/.test(sessionRef)
      ? {authEpoch: Number(authEpoch), sessionRef} : {};
    return { role, userId: Number(userId), ...auth, ...(email ? { email } : {}), ...(nickname ? { nickname } : {}), requestId, bridge: "ok" };
  } catch {
    console.info("[viewer] introspection unavailable");
    return fallback("error");
  }
}

function isRole(value: unknown): value is ViewerRole { return value === "guest" || value === "user" || value === "admin"; }
function isLoopback(hostname: string): boolean { return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1" || hostname === "[::1]"; }
