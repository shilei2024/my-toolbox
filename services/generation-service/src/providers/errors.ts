export const PROVIDER_ERROR_CATEGORIES = [
  "configuration",
  "authentication",
  "validation",
  "content_policy",
  "rate_limit",
  "timeout",
  "unavailable",
  "upstream",
  "cancelled",
  "unsupported",
  "unknown",
] as const;

export type ProviderErrorCategory = (typeof PROVIDER_ERROR_CATEGORIES)[number];

const RETRYABLE_CATEGORIES = new Set<ProviderErrorCategory>([
  "rate_limit",
  "timeout",
  "unavailable",
  "upstream",
]);

export interface ProviderErrorOptions {
  readonly providerCode: string;
  readonly category: ProviderErrorCategory;
  readonly code: string;
  readonly message: string;
  readonly retryable?: boolean;
  readonly externalRequestId?: string;
  readonly statusCode?: number;
  readonly cause?: unknown;
}

export class ProviderError extends Error {
  readonly providerCode: string;
  readonly category: ProviderErrorCategory;
  readonly code: string;
  readonly retryable: boolean;
  readonly externalRequestId: string | undefined;
  readonly statusCode: number | undefined;

  constructor(options: ProviderErrorOptions) {
    super(options.message, { cause: options.cause });
    this.name = "ProviderError";
    this.providerCode = options.providerCode;
    this.category = options.category;
    this.code = options.code;
    this.retryable = options.retryable ?? RETRYABLE_CATEGORIES.has(options.category);
    this.externalRequestId = options.externalRequestId;
    this.statusCode = options.statusCode;
  }

  toSafeRecord(): Record<string, string | number | boolean | undefined> {
    return {
      providerCode: this.providerCode,
      category: this.category,
      code: this.code,
      message: this.message,
      retryable: this.retryable,
      externalRequestId: this.externalRequestId,
      statusCode: this.statusCode,
    };
  }
}

export class NoEligibleProviderError extends Error {
  constructor(message = "No eligible image provider satisfies this request") {
    super(message);
    this.name = "NoEligibleProviderError";
  }
}

export function normalizeProviderError(error: unknown, providerCode: string): ProviderError {
  if (error instanceof ProviderError) {
    return error;
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return new ProviderError({
      providerCode,
      category: "cancelled",
      code: "request_aborted",
      message: "Provider request was cancelled",
      retryable: false,
      cause: error,
    });
  }
  return new ProviderError({
    providerCode,
    category: "unknown",
    code: "provider_unknown_error",
    message: "Image provider request failed",
    retryable: false,
    cause: error,
  });
}
