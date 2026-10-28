/**
 * Unified admin entry helpers.
 *
 * The Gallery module no longer hosts its own admin console: /admin redirects
 * to the main-site admin (MAVIS_ADMIN_URL). NEXT_PUBLIC_MAVIS_ADMIN_URL is the
 * same value, safe to inline into the client header for the admin shortcut.
 */

export function adminConsoleUrl(env: NodeJS.ProcessEnv = process.env): string | undefined {
  return safeAdminUrl(env.MAVIS_ADMIN_URL);
}

export function publicAdminConsoleUrl(env: NodeJS.ProcessEnv = process.env): string | undefined {
  return safeAdminUrl(env.NEXT_PUBLIC_MAVIS_ADMIN_URL);
}

function safeAdminUrl(raw?: string): string | undefined {
  const value = raw?.trim();
  if (!value) return undefined;
  try {
    const url = new URL(value);
    if (url.protocol === "https:" || (url.protocol === "http:" && isLoopback(url.hostname))) {
      return url.toString();
    }
  } catch {
    // Malformed values are ignored; the admin entry simply stays hidden.
  }
  return undefined;
}

function isLoopback(hostname: string): boolean {
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1" || hostname === "[::1]";
}
