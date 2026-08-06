// MindfulPenpal API relay
//
// Gallery (Vercel) -> Cloudflare Worker -> api-ai.mindfulpenpal.com
//
// Why: Vercel Functions (us-east-1) can be unstable when fetching a mainland
// China origin directly. A Cloudflare Worker runs on Cloudflare's edge, which
// has more reliable international routes, and retries transient failures.
//
// Deploy: Cloudflare dashboard -> Workers & Pages -> Create Worker -> paste
// this file, then set GALLERY_SERVICE_BASE_URL to the workers.dev URL.

const DEFAULT_ORIGIN = "https://api-ai.mindfulpenpal.com";
const MAX_ATTEMPTS = 3;
const TIMEOUT_MS = 20_000;

export default {
  async fetch(request, env) {
    const origin = (env.API_ORIGIN || DEFAULT_ORIGIN).replace(/\/+$/, "");
    const url = new URL(request.url);
    const target = new URL(url.pathname + url.search, origin);
    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.set("x-forwarded-host", url.host);

    let lastError;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
      try {
        const response = await fetch(target, {
          method: request.method,
          headers,
          body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
          redirect: "manual",
          signal: controller.signal,
        });
        return response;
      } catch (error) {
        lastError = error;
        if (attempt < MAX_ATTEMPTS) {
          await new Promise((resolve) => setTimeout(resolve, 500 * attempt));
        }
      } finally {
        clearTimeout(timer);
      }
    }
    return Response.json(
      { error: { code: "service_unavailable", message: "upstream unreachable" } },
      { status: 503 },
    );
  },
};
