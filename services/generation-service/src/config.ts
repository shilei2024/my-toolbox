import path from "node:path";

export interface ComfyUIConfig {
  readonly baseUrl: string;
  readonly authToken?: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly requestTimeoutMs: number;
  readonly downloadTimeoutMs: number;
  /** Max bytes of a single ComfyUI output (image/video) streamed to disk. */
  readonly maxOutputBytes: number;
  readonly retryCount: number;
  readonly retryDelayMs: number;
  readonly pollIntervalMs: number;
  readonly pollMaxAttempts: number;
  readonly allowGlobalInterrupt: boolean;
  readonly workflowDirectory: string;
  readonly downloadDirectory: string;
}

export interface TencentCosConfig {
  readonly secretId: string;
  readonly secretKey: string;
  readonly securityToken?: string;
  readonly bucket: string;
  readonly region: string;
  readonly cdnBaseUrl?: string;
}

export interface Phase4Config {
  readonly comfyui: ComfyUIConfig;
  readonly cos: TencentCosConfig;
  readonly logPrompts: boolean;
}

export class ConfigurationError extends Error {
  readonly key: string;

  constructor(key: string, message = `Missing or invalid environment variable: ${key}`) {
    super(message);
    this.name = "ConfigurationError";
    this.key = key;
  }
}

export function loadPhase4Config(env: NodeJS.ProcessEnv = process.env): Phase4Config {
  const baseUrl = required(env, "COMFYUI_BASE_URL");
  const authToken = optional(env, "COMFYUI_AUTH_TOKEN");
  assertHttpUrl("COMFYUI_BASE_URL", baseUrl);
  const workflowDirectory = absolutePath(env, "COMFYUI_WORKFLOW_DIR");
  const downloadDirectory = absolutePath(env, "COMFYUI_DOWNLOAD_DIR");
  const cdnBaseUrl = optional(env, "COS_CDN_BASE_URL");
  const securityToken = optional(env, "COS_SECURITY_TOKEN");
  if (cdnBaseUrl) assertHttpUrl("COS_CDN_BASE_URL", cdnBaseUrl);
  return {
    comfyui: {
      baseUrl: baseUrl.replace(/\/+$/, ""),
      ...(authToken ? { authToken } : {}),
      headers: jsonStringMap(env, "COMFYUI_HEADERS_JSON", {}),
      requestTimeoutMs: positiveInt(env, "COMFYUI_REQUEST_TIMEOUT_MS"),
      downloadTimeoutMs: positiveInt(env, "COMFYUI_DOWNLOAD_TIMEOUT_MS"),
      maxOutputBytes: positiveInt(env, "COMFYUI_MAX_OUTPUT_BYTES", 100 * 1024 * 1024),
      retryCount: nonNegativeInt(env, "COMFYUI_RETRY_COUNT"),
      retryDelayMs: nonNegativeInt(env, "COMFYUI_RETRY_DELAY_MS"),
      pollIntervalMs: positiveInt(env, "COMFYUI_POLL_INTERVAL_MS"),
      pollMaxAttempts: positiveInt(env, "COMFYUI_POLL_MAX_ATTEMPTS"),
      allowGlobalInterrupt: booleanValue(env, "COMFYUI_ALLOW_GLOBAL_INTERRUPT"),
      workflowDirectory,
      downloadDirectory,
    },
    cos: {
      secretId: required(env, "COS_SECRET_ID"),
      secretKey: required(env, "COS_SECRET_KEY"),
      ...(securityToken ? { securityToken } : {}),
      bucket: required(env, "COS_BUCKET"),
      region: required(env, "COS_REGION"),
      ...(cdnBaseUrl ? { cdnBaseUrl: cdnBaseUrl.replace(/\/+$/, "") } : {}),
    },
    logPrompts: booleanValue(env, "GENERATION_LOG_PROMPTS"),
  };
}

function required(env: NodeJS.ProcessEnv, key: string): string {
  const value = env[key]?.trim();
  if (!value) throw new ConfigurationError(key);
  return value;
}

function optional(env: NodeJS.ProcessEnv, key: string): string | undefined {
  return env[key]?.trim() || undefined;
}

function positiveInt(env: NodeJS.ProcessEnv, key: string, fallback?: number): number {
  const raw = env[key]?.trim();
  const value = raw ? Number(raw) : fallback;
  if (value === undefined || !Number.isInteger(value) || value <= 0) throw new ConfigurationError(key);
  return value;
}

function nonNegativeInt(env: NodeJS.ProcessEnv, key: string): number {
  const value = Number(required(env, key));
  if (!Number.isInteger(value) || value < 0) throw new ConfigurationError(key);
  return value;
}

function booleanValue(env: NodeJS.ProcessEnv, key: string): boolean {
  const value = required(env, key).toLowerCase();
  if (value === "true") return true;
  if (value === "false") return false;
  throw new ConfigurationError(key);
}

function absolutePath(env: NodeJS.ProcessEnv, key: string): string {
  const value = required(env, key);
  if (!path.isAbsolute(value)) throw new ConfigurationError(key, `${key} must be an absolute path`);
  return path.resolve(value);
}

function assertHttpUrl(key: string, value: string): void {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConfigurationError(key, `${key} must be a valid URL`);
  }
  if (!new Set(["http:", "https:"]).has(url.protocol)) throw new ConfigurationError(key, `${key} must use HTTP or HTTPS`);
}

function jsonStringMap(env: NodeJS.ProcessEnv, key: string, fallback: Record<string, string>): Record<string, string> {
  const raw = optional(env, key);
  if (!raw) return fallback;
  try {
    const value = JSON.parse(raw) as unknown;
    if (!value || Array.isArray(value) || typeof value !== "object") throw new Error();
    if (!Object.values(value).every((item) => typeof item === "string")) throw new Error();
    return value as Record<string, string>;
  } catch {
    throw new ConfigurationError(key, `${key} must be a JSON object containing string values`);
  }
}
