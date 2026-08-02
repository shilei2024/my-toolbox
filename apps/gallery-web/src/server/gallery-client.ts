import "server-only";

import { createHmac } from "node:crypto";
import type { GalleryImageDetail, GalleryPageData, GalleryQuery, ViewerContext } from "@/lib/gallery-types";

export class GalleryClientError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(code: string, message: string, status: number) { super(message); this.name = "GalleryClientError"; this.code = code; this.status = status; }
}

export async function getPublicGallery(query: GalleryQuery, viewer: ViewerContext): Promise<GalleryPageData> {
  return serviceRequest<GalleryPageData>(`/v1/gallery${queryString(query)}`, viewer);
}

export async function getGalleryDetail(slug: string, viewer: ViewerContext): Promise<GalleryImageDetail> {
  return serviceRequest<GalleryImageDetail>(`/v1/gallery/${encodeURIComponent(slug)}`, viewer);
}

export async function getMyImages(query: GalleryQuery, viewer: ViewerContext): Promise<GalleryPageData> {
  return serviceRequest<GalleryPageData>(`/v1/me/images${queryString(query)}`, viewer);
}

export async function getFavorites(query: GalleryQuery, viewer: ViewerContext): Promise<GalleryPageData> {
  return serviceRequest<GalleryPageData>(`/v1/me/favorites${queryString(query)}`, viewer);
}

export async function serviceRequest<T>(path: string, viewer: ViewerContext, init: RequestInit = {}): Promise<T> {
  const base = serviceBaseUrl();
  const secret = internalSecret();
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    v: 1,
    role: viewer.role,
    ...(viewer.userId ? { userId: viewer.userId } : {}),
    requestId: viewer.requestId,
    issuedAt: now,
    expiresAt: now + 60,
  };
  const context = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature = createHmac("sha256", secret).update(context).digest("base64url");
  const response = await fetch(new URL(path, base), {
    ...init,
    cache: "no-store",
    signal: AbortSignal.timeout(8_000),
    headers: {
      Accept: "application/json",
      "X-Mavis-User-Context": context,
      "X-Mavis-User-Signature": signature,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  }).catch(() => { throw new GalleryClientError("service_unavailable", "Gallery service is temporarily unavailable", 503); });

  const contentType = response.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json") ? await response.json() as unknown : undefined;
  if (!response.ok) {
    const safe = safeError(body);
    throw new GalleryClientError(safe.code, safe.message, response.status);
  }
  return body as T;
}

export function safeProxyError(error: unknown): Response {
  const normalized = error instanceof GalleryClientError ? error : new GalleryClientError("service_unavailable", "Gallery service is temporarily unavailable", 503);
  return Response.json({ error: { code: normalized.code, message: normalized.message } }, { status: normalized.status });
}

function serviceBaseUrl(): URL {
  const raw = process.env.GALLERY_SERVICE_BASE_URL?.trim();
  if (!raw) throw new GalleryClientError("service_unavailable", "Gallery service is not configured", 503);
  let url: URL;
  try { url = new URL(raw.endsWith("/") ? raw : `${raw}/`); } catch { throw new GalleryClientError("service_unavailable", "Gallery service is not configured", 503); }
  if (url.protocol !== "https:" && !(url.protocol === "http:" && isLoopback(url.hostname))) throw new GalleryClientError("service_unavailable", "Gallery service is not configured", 503);
  return url;
}

function internalSecret(): string {
  const secret = process.env.GALLERY_INTERNAL_HMAC_SECRET?.trim() ?? "";
  if (Buffer.byteLength(secret, "utf8") < 32) throw new GalleryClientError("service_unavailable", "Gallery service is not configured", 503);
  return secret;
}

function queryString(query: GalleryQuery): string {
  const params = new URLSearchParams();
  if (query.cursor) params.set("cursor", query.cursor);
  if (query.limit) params.set("limit", String(query.limit));
  if (query.q) params.set("q", query.q);
  if (query.tag) params.set("tag", query.tag);
  if (query.workflow) params.set("workflow", query.workflow);
  if (query.orientation) params.set("orientation", query.orientation);
  const result = params.toString();
  return result ? `?${result}` : "";
}

function safeError(value: unknown): { code: string; message: string } {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const error = (value as { error?: unknown }).error;
    if (error && typeof error === "object" && !Array.isArray(error)) {
      const code = (error as { code?: unknown }).code;
      const message = (error as { message?: unknown }).message;
      if (typeof code === "string" && typeof message === "string") return { code, message };
    }
  }
  return { code: "service_unavailable", message: "Gallery service is temporarily unavailable" };
}

function isLoopback(hostname: string): boolean { return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1" || hostname === "[::1]"; }
