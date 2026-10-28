import "server-only";

import type { ViewerContext } from "@/lib/gallery-types";

type RateLimit = { count: number; resetAt: number };

const buckets = new Map<string, RateLimit>();
const MAX_BUCKETS = 10_000;

export function requireViewerRole(viewer: ViewerContext, required: "user" | "admin"): Response | undefined {
  if (required === "admin" && viewer.role !== "admin") {
    return Response.json({ error: { code: "forbidden", message: "你没有执行此操作的权限。" } }, { status: 403 });
  }
  if (required === "user" && viewer.role === "guest") {
    return Response.json({ error: { code: "unauthorized", message: "请先登录后再继续。" } }, { status: 401 });
  }
  return undefined;
}

/**
 * Best-effort local BFF throttling. It is deliberately an extra protection:
 * the Generation Service remains the authoritative distributed rate limiter.
 */
export function checkRateLimit(request: Request, viewer: ViewerContext, scope: string, limit: number, windowMs = 60_000): Response | undefined {
  const now = Date.now();
  if (buckets.size > MAX_BUCKETS) {
    for (const [key, bucket] of buckets) if (bucket.resetAt <= now) buckets.delete(key);
  }
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  const identity = viewer.userId ? `user:${viewer.userId}` : `ip:${forwarded || "unknown"}`;
  const key = `${scope}:${identity}`;
  const current = buckets.get(key);
  if (!current || current.resetAt <= now) {
    buckets.set(key, { count: 1, resetAt: now + windowMs });
    return undefined;
  }
  if (current.count >= limit) {
    return Response.json(
      { error: { code: "rate_limited", message: "操作过于频繁，请稍后重试。" } },
      { status: 429, headers: { "Retry-After": String(Math.max(1, Math.ceil((current.resetAt - now) / 1000))) } },
    );
  }
  current.count += 1;
  return undefined;
}

export function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  const configured = process.env.GALLERY_PUBLIC_ORIGIN?.trim();
  try {
    // Prefer the explicitly configured public origin: it is stable across
    // hosts, ports and deployments. When it is missing, fall back to the
    // request URL origin, which is derived from the Host the client actually
    // reached — never from the Origin header itself, so an attacker cannot
    // make a request "same-origin" by echoing a target origin.
    const expected = configured || new URL(request.url).origin;
    return new URL(origin).origin === new URL(expected).origin;
  } catch {
    return false;
  }
}
