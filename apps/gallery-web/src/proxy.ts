import { NextRequest, NextResponse } from "next/server";

/**
 * Per-request Content Security Policy with a fresh nonce.
 *
 * The Next.js App Router streams part of the HTML and reveals it with inline
 * scripts (the `$RS` stream-reveal helpers). A static policy such as
 * `default-src 'self'` blocks those inline scripts, so the page stays stuck on
 * the loading skeleton and never shows the rendered content. A per-request
 * nonce lets Next.js tag its own inline scripts and JS bundles while still
 * blocking injected third-party scripts.
 *
 * Artwork URLs point at Tencent COS/CDN over HTTPS. The Generation Service
 * already validates every asset URL against the configured COS/CDN host
 * allowlist before the browser receives it, so `img-src https:` is safe here
 * and intentionally does not duplicate the backend allowlist.
 */
export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDev = process.env.NODE_ENV === "development";
  const cspHeader = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' https: data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", cspHeader);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", cspHeader);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
