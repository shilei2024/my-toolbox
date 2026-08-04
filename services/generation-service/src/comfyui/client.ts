import { createWriteStream } from "node:fs";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { ComfyUIConfig } from "../config.ts";
import { ProviderError } from "../providers/errors.ts";
import type { JsonObject } from "../providers/types.ts";

export interface ComfyImageRef { readonly filename: string; readonly subfolder: string; readonly type: string }
export interface ComfyHistoryEntry { readonly status?: { readonly completed?: boolean; readonly status_str?: string; readonly messages?: unknown[] }; readonly outputs?: Record<string, { readonly images?: ComfyImageRef[] }> }
export interface ComfyRetryEvent { readonly path: string; readonly retryNumber: number; readonly retryLimit: number; readonly failureCode: string }
export type ComfyRetryObserver = (event: ComfyRetryEvent) => void;

export class ComfyUIClient {
  readonly config: ComfyUIConfig;
  readonly #fetcher: typeof fetch;
  readonly #onRetry: ComfyRetryObserver;
  constructor(config: ComfyUIConfig, fetcher: typeof fetch = fetch, onRetry: ComfyRetryObserver = () => undefined) { this.config = config; this.#fetcher = fetcher; this.#onRetry = onRetry; }

  async queuePrompt(workflow: JsonObject, clientId: string, signal?: AbortSignal): Promise<string> {
    const data = await this.#json("/prompt", { method: "POST", body: JSON.stringify({ prompt: workflow, client_id: clientId }), ...(signal ? { signal } : {}) });
    const id = isObject(data) && typeof data.prompt_id === "string" ? data.prompt_id : undefined;
    if (!id) throw this.#error("upstream", "invalid_prompt_response", "ComfyUI returned an invalid prompt response");
    return id;
  }

  async getHistory(promptId: string, signal?: AbortSignal): Promise<ComfyHistoryEntry | undefined> {
    const data = await this.#json(`/history/${encodeURIComponent(promptId)}`, { method: "GET", ...(signal ? { signal } : {}) });
    return isObject(data) ? data[promptId] as ComfyHistoryEntry | undefined : undefined;
  }

  async downloadImage(image: ComfyImageRef, destination: string, signal?: AbortSignal): Promise<void> {
    const query = new URLSearchParams({ filename: image.filename, subfolder: image.subfolder, type: image.type });
    const response = await this.#request(`/view?${query}`, { method: "GET", ...(signal ? { signal } : {}) }, this.config.downloadTimeoutMs);
    if (!response.body) throw this.#error("upstream", "empty_image_body", "ComfyUI returned an empty image");
    await mkdir(path.dirname(destination), { recursive: true });
    try { await pipeline(Readable.fromWeb(response.body as never), createWriteStream(destination)); }
    catch (error) { await rm(destination, { force: true }); throw this.#error("upstream", "image_download_failed", "ComfyUI image download failed", error); }
  }

  async cancelPrompt(promptId: string, signal?: AbortSignal): Promise<boolean> {
    await this.#json("/queue", { method: "POST", body: JSON.stringify({ delete: [promptId] }), ...(signal ? { signal } : {}) });
    if (this.config.allowGlobalInterrupt) await this.#json("/interrupt", { method: "POST", body: "{}", ...(signal ? { signal } : {}) });
    return true;
  }

  async healthCheck(signal?: AbortSignal): Promise<number> {
    const started = Date.now();
    await this.#json("/history", { method: "GET", ...(signal ? { signal } : {}) });
    return Date.now() - started;
  }

  async #json(pathname: string, init: RequestInit): Promise<unknown> {
    const response = await this.#request(pathname, init, this.config.requestTimeoutMs);
    try { return await response.json(); }
    catch (error) { throw this.#error("upstream", "invalid_json", "ComfyUI returned invalid JSON", error); }
  }

  async #request(pathname: string, init: RequestInit, timeoutMs: number): Promise<Response> {
    let lastError: unknown;
    for (let attempt = 0; attempt <= this.config.retryCount; attempt += 1) {
      const timeout = AbortSignal.timeout(timeoutMs);
      const signal = init.signal ? AbortSignal.any([init.signal, timeout]) : timeout;
      try {
        const response = await this.#fetcher(`${this.config.baseUrl}${pathname}`, {
          ...init,
          signal,
          headers: { "content-type": "application/json", ...this.config.headers, ...(this.config.authToken ? { authorization: `Bearer ${this.config.authToken}` } : {}) },
        });
        if (response.ok) return response;
        const retryable = response.status === 429 || response.status >= 500;
        if (!retryable || attempt === this.config.retryCount) throw this.#error(response.status === 401 || response.status === 403 ? "authentication" : retryable ? "unavailable" : "validation", `http_${response.status}`, "ComfyUI request failed", undefined, response.status, retryable);
      } catch (error) {
        if (error instanceof ProviderError) { lastError = error; if (!error.retryable || attempt === this.config.retryCount) throw error; }
        else { lastError = error; if (attempt === this.config.retryCount) throw this.#error(error instanceof DOMException && error.name === "TimeoutError" ? "timeout" : "unavailable", "network_error", "ComfyUI is unavailable", error); }
      }
      this.#onRetry({ path: pathname, retryNumber: attempt + 1, retryLimit: this.config.retryCount, failureCode: lastError instanceof ProviderError ? lastError.code : "network_error" });
      await new Promise((resolve) => setTimeout(resolve, this.config.retryDelayMs));
    }
    throw this.#error("unavailable", "request_failed", "ComfyUI is unavailable", lastError);
  }

  #error(category: "authentication" | "validation" | "timeout" | "unavailable" | "upstream", code: string, message: string, cause?: unknown, statusCode?: number, retryable?: boolean): ProviderError {
    return new ProviderError({ providerCode: "comfyui", category, code, message, ...(cause ? { cause } : {}), ...(statusCode ? { statusCode } : {}), ...(retryable === undefined ? {} : { retryable }) });
  }
}

function isObject(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
