import { ProviderError } from "../providers/errors.ts";

export interface RemoteProviderHttpConfig {
  readonly providerCode: string;
  readonly baseUrl: string;
  readonly apiKey: string;
  readonly requestTimeoutMs: number;
  readonly maxResponseBytes: number;
}

export interface RemoteJsonResponse {
  readonly data: unknown;
  readonly requestId?: string;
}

export class RemoteHttpResponseError extends Error {
  readonly statusCode: number;
  readonly data: unknown;
  readonly requestId: string | undefined;

  constructor(statusCode: number, data: unknown, requestId?: string) {
    super("Remote provider returned an unsuccessful HTTP response");
    this.name = "RemoteHttpResponseError";
    this.statusCode = statusCode;
    this.data = data;
    this.requestId = requestId;
  }
}

export async function requestRemoteJson(
  config: RemoteProviderHttpConfig,
  pathname: string,
  init: RequestInit,
  fetcher: typeof fetch,
): Promise<RemoteJsonResponse> {
  const timeout = AbortSignal.timeout(config.requestTimeoutMs);
  const signal = init.signal ? AbortSignal.any([init.signal, timeout]) : timeout;
  let response: Response;
  try {
    response = await fetcher(joinUrl(config.baseUrl, pathname), { ...init, signal });
  } catch (error) {
    if (init.signal?.aborted) {
      throw new ProviderError({ providerCode: config.providerCode, category: "cancelled", code: "request_aborted", message: "Provider request was cancelled", retryable: false, cause: error });
    }
    if (timeout.aborted) {
      throw new ProviderError({ providerCode: config.providerCode, category: "timeout", code: "provider_timeout", message: "Provider request timed out", retryable: true, cause: error });
    }
    throw new ProviderError({ providerCode: config.providerCode, category: "unavailable", code: "provider_network_failure", message: "Provider connection failed", retryable: true, cause: error });
  }

  const requestId = header(response, "x-request-id") ?? header(response, "x-goog-request-id") ?? header(response, "x-tt-logid");
  const data = await readBoundedJson(response, config);
  if (!response.ok) throw new RemoteHttpResponseError(response.status, data, requestId);
  return { data, ...(requestId ? { requestId } : {}) };
}

export function mapRemoteHttpError(
  error: unknown,
  providerCode: string,
  isContentPolicyError: (data: unknown) => boolean,
): ProviderError {
  if (error instanceof ProviderError) return error;
  if (!(error instanceof RemoteHttpResponseError)) {
    return new ProviderError({ providerCode, category: "unknown", code: "provider_unknown_error", message: "Generation provider request failed", retryable: false, cause: error });
  }
  const upstreamCode = safeErrorCode(error.data);
  if (isContentPolicyError(error.data)) {
    return new ProviderError({ providerCode, category: "content_policy", code: "content_policy_blocked", message: "Generation was blocked by provider safety policy", retryable: false, statusCode: error.statusCode, ...(error.requestId ? { externalRequestId: error.requestId } : {}), cause: error });
  }
  const category = error.statusCode === 401 || error.statusCode === 403
    ? "authentication"
    : error.statusCode === 429
      ? "rate_limit"
      : error.statusCode >= 500
        ? "unavailable"
        : "validation";
  const retryable = error.statusCode === 429 || error.statusCode >= 500;
  return new ProviderError({
    providerCode,
    category,
    code: upstreamCode ? `http_${error.statusCode}_${upstreamCode}` : `http_${error.statusCode}`,
    message: category === "authentication" ? "Provider authentication failed" : retryable ? "Provider is temporarily unavailable" : "Provider rejected the generation request",
    retryable,
    statusCode: error.statusCode,
    ...(error.requestId ? { externalRequestId: error.requestId } : {}),
    cause: error,
  });
}

export function joinUrl(baseUrl: string, pathname: string): string {
  return `${baseUrl.replace(/\/+$/, "")}/${pathname.replace(/^\/+/, "")}`;
}

function header(response: Response, name: string): string | undefined {
  return response.headers.get(name)?.trim() || undefined;
}

async function readBoundedJson(response: Response, config: RemoteProviderHttpConfig): Promise<unknown> {
  const declared = Number(response.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > config.maxResponseBytes) throw oversized(config.providerCode);
  if (!response.body) return {};
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const item = await reader.read();
      if (item.done) break;
      total += item.value.byteLength;
      if (total > config.maxResponseBytes) {
        await reader.cancel();
        throw oversized(config.providerCode);
      }
      chunks.push(item.value);
    }
  } finally {
    reader.releaseLock();
  }
  if (total === 0) return {};
  try { return JSON.parse(Buffer.concat(chunks.map((chunk) => Buffer.from(chunk)), total).toString("utf8")) as unknown; }
  catch (error) { throw new ProviderError({ providerCode: config.providerCode, category: "upstream", code: "invalid_json", message: "Provider returned invalid JSON", retryable: false, cause: error }); }
}

function oversized(providerCode: string): ProviderError {
  return new ProviderError({ providerCode, category: "upstream", code: "response_too_large", message: "Provider response exceeded the configured limit", retryable: false });
}

function safeErrorCode(data: unknown): string | undefined {
  if (!isObject(data)) return undefined;
  const error = isObject(data.error) ? data.error : data;
  const value = typeof error.code === "string" ? error.code : typeof error.type === "string" ? error.type : undefined;
  if (!value) return undefined;
  const safe = value.toLowerCase().replace(/[^a-z0-9_-]+/g, "_").slice(0, 64);
  return safe || undefined;
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
