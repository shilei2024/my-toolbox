export function safeAuthReturnUrl(value?: string, configuredOrigin?: string): string | undefined {
  if (!value) return undefined;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  if (!configuredOrigin) return undefined;
  try {
    const candidate = new URL(value);
    const expected = new URL(configuredOrigin);
    const loopbackHttp =
      candidate.protocol === "http:" &&
      expected.protocol === "http:" &&
      isLoopbackHost(candidate.hostname) &&
      isLoopbackHost(expected.hostname);
    if ((candidate.protocol === "https:" || loopbackHttp) && candidate.origin === expected.origin) return value;
  } catch { /* Ignore malformed URLs. */ }
  return undefined;
}

export function isLoopbackHost(hostname: string): boolean {
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1" || hostname === "[::1]";
}
