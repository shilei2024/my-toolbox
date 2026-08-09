import "server-only";
import { isLoopbackHost, safeAuthReturnUrl } from "@/lib/auth-return-url";

/**
 * Authentication lives on the existing Flask toolbox site. The Gallery Web
 * only redirects there; the Flask session cookie is then read through
 * MAVIS_AUTH_INTROSPECTION_URL. Configure MAVIS_AUTH_LOGIN_URL / LOGOUT_URL to
 * enable the header and pricing login entry points.
 */

export function loginUrl(next?: string): string | undefined {
  const base = configuredAuthUrl("MAVIS_AUTH_LOGIN_URL");
  if (!base) return undefined;
  return appendNext(base, next);
}

export function logoutUrl(returnTo?: string): string | undefined {
  const base = configuredAuthUrl("MAVIS_AUTH_LOGOUT_URL");
  if (!base) return undefined;
  const next = safeAuthReturnUrl(returnTo, process.env.GALLERY_PUBLIC_ORIGIN?.trim());
  return next ? `${base}${base.includes("?") ? "&" : "?"}next=${encodeURIComponent(next)}` : base;
}

function configuredAuthUrl(name: string): string | undefined {
  const raw = process.env[name]?.trim();
  if (!raw) return undefined;
  let url: URL;
  try { url = new URL(raw); } catch { return undefined; }
  if (url.protocol !== "https:" && !(url.protocol === "http:" && isLoopback(url.hostname))) return undefined;
  return url.toString();
}

function appendNext(base: string, next?: string): string {
  const safe = safeAuthReturnUrl(next, process.env.GALLERY_PUBLIC_ORIGIN?.trim());
  if (!safe) return base;
  return `${base}${base.includes("?") ? "&" : "?"}next=${encodeURIComponent(safe)}`;
}

function isLoopback(hostname: string): boolean {
  return isLoopbackHost(hostname);
}
