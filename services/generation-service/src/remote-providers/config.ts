import { ConfigurationError } from "../config.ts";
import type { RemoteProviderHttpConfig } from "./http.ts";

export interface Phase9RemoteProviderConfig {
  readonly openai?: RemoteProviderHttpConfig;
  readonly gemini?: RemoteProviderHttpConfig;
  readonly jimeng?: RemoteProviderHttpConfig;
  readonly arkVideo?: RemoteProviderHttpConfig;
}

export function loadPhase9RemoteProviderConfig(env: NodeJS.ProcessEnv = process.env): Phase9RemoteProviderConfig {
  const enabled = ["OPENAI", "GEMINI", "JIMENG", "ARK_VIDEO"].filter((name) => optional(env, `${name}_API_KEY`));
  if (enabled.length === 0) return {};
  const requestTimeoutMs = positiveInt(env, "REMOTE_PROVIDER_REQUEST_TIMEOUT_MS");
  const maxResponseBytes = positiveInt(env, "REMOTE_PROVIDER_MAX_RESPONSE_BYTES");
  return {
    ...provider(env, "OPENAI", "openai", requestTimeoutMs, maxResponseBytes),
    ...provider(env, "GEMINI", "gemini", requestTimeoutMs, maxResponseBytes),
    ...provider(env, "JIMENG", "jimeng", requestTimeoutMs, maxResponseBytes),
    ...provider(env, "ARK_VIDEO", "arkVideo", requestTimeoutMs, maxResponseBytes),
  };
}

function provider(env: NodeJS.ProcessEnv, prefix: "OPENAI" | "GEMINI" | "JIMENG" | "ARK_VIDEO", code: "openai" | "gemini" | "jimeng" | "arkVideo", requestTimeoutMs: number, maxResponseBytes: number): Partial<Phase9RemoteProviderConfig> {
  const apiKey = optional(env, `${prefix}_API_KEY`);
  if (!apiKey) return {};
  const baseUrl = required(env, `${prefix}_BASE_URL`);
  assertHttpUrl(`${prefix}_BASE_URL`, baseUrl);
  return { [code]: { providerCode: code, baseUrl: baseUrl.replace(/\/+$/, ""), apiKey, requestTimeoutMs, maxResponseBytes } };
}

function required(env: NodeJS.ProcessEnv, key: string): string {
  const value = optional(env, key);
  if (!value) throw new ConfigurationError(key);
  return value;
}

function optional(env: NodeJS.ProcessEnv, key: string): string | undefined { return env[key]?.trim() || undefined; }
function positiveInt(env: NodeJS.ProcessEnv, key: string): number { const value = Number(required(env, key)); if (!Number.isInteger(value) || value <= 0) throw new ConfigurationError(key); return value; }
function assertHttpUrl(key: string, value: string): void { let url: URL; try { url = new URL(value); } catch { throw new ConfigurationError(key, `${key} must be a valid URL`); } if (url.protocol !== "https:" && url.protocol !== "http:") throw new ConfigurationError(key, `${key} must use HTTP or HTTPS`); }
