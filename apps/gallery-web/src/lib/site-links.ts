import { isLoopbackHost } from "./auth-return-url.ts";

export function mainSiteUrl(env: NodeJS.ProcessEnv = process.env): string | undefined {
  const configured = safeSiteUrl(env.MAVIS_SITE_URL) ?? safeSiteUrl(env.MAVIS_AUTH_LOGIN_URL);
  if (!configured) return undefined;
  return new URL("/", configured).toString();
}

function safeSiteUrl(raw?: string): string | undefined {
  const value = raw?.trim();
  if (!value) return undefined;
  try {
    const url = new URL(value);
    if (url.protocol === "https:" || (url.protocol === "http:" && isLoopbackHost(url.hostname))) return url.toString();
  } catch {
    // Invalid configuration stays hidden instead of creating an unsafe link.
  }
  return undefined;
}
