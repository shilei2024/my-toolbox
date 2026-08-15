import COS from "cos-nodejs-sdk-v5";
import type { TencentCosConfig } from "../config.ts";
import type { StorageProvider, StorageUpload, StoredAsset } from "./storage-provider.ts";

interface CosClient {
  putObject(options: Record<string, unknown>, callback: (error: Error | null, data?: { ETag?: string }) => void): void;
  getObject(options: Record<string, unknown>, callback: (error: Error | null, data?: { Body?: Buffer | string }) => void): void;
  deleteObject(options: Record<string, unknown>, callback: (error: Error | null) => void): void;
  getBucket(options: Record<string, unknown>, callback: (error: Error | null, data?: { Contents?: Array<{ Key?: string; LastModified?: string }>; IsTruncated?: boolean; NextMarker?: string }) => void): void;
}

export class TencentCosStorage implements StorageProvider {
  readonly code = "tencent_cos";
  readonly #client: CosClient;
  readonly config: TencentCosConfig;
  constructor(config: TencentCosConfig, client?: CosClient) { this.config = config; this.#client = client ?? new COS({ SecretId: config.secretId, SecretKey: config.secretKey, ...(config.securityToken ? { SecurityToken: config.securityToken } : {}) }) as unknown as CosClient; }
  async upload(input: StorageUpload): Promise<StoredAsset> {
    const data = await new Promise<{ ETag?: string }>((resolve, reject) => this.#client.putObject({ Bucket: this.config.bucket, Region: this.config.region, Key: input.objectKey, Body: input.body, ContentType: input.contentType, ...(input.contentLength === undefined ? {} : { ContentLength: input.contentLength }), ...(input.metadata ? { Headers: Object.fromEntries(Object.entries(input.metadata).map(([key, value]) => [`x-cos-meta-${sanitizeMetadataKey(key)}`, value])) } : {}) }, (error, result) => error ? reject(new Error("Tencent COS upload failed", { cause: error })) : resolve(result ?? {})));
    return { storageProvider: this.code, bucket: this.config.bucket, region: this.config.region, objectKey: input.objectKey, url: `${this.config.cdnBaseUrl ?? `https://${this.config.bucket}.cos.${this.config.region}.myqcloud.com`}/${encodeKey(input.objectKey)}`, ...(data.ETag ? { etag: data.ETag } : {}) };
  }
  async download(objectKey: string): Promise<Buffer> {
    const data = await new Promise<{ Body?: Buffer | string }>((resolve, reject) => this.#client.getObject({ Bucket: this.config.bucket, Region: this.config.region, Key: objectKey }, (error, result) => error ? reject(new Error("Tencent COS download failed", { cause: error })) : resolve(result ?? {})));
    if (typeof data.Body === "string") return Buffer.from(data.Body);
    if (Buffer.isBuffer(data.Body)) return data.Body;
    throw new Error("Tencent COS download returned an empty body");
  }
  async delete(objectKey: string): Promise<void> { await new Promise<void>((resolve, reject) => this.#client.deleteObject({ Bucket: this.config.bucket, Region: this.config.region, Key: objectKey }, (error) => error ? reject(new Error("Tencent COS delete failed", { cause: error })) : resolve())); }

  async list(prefix: string): Promise<readonly string[]> {
    const keys: string[] = [];
    let marker: string | undefined;
    for (let page = 0; page < 1000; page += 1) {
      const data = await new Promise<{ Contents?: Array<{ Key?: string }>; IsTruncated?: boolean; NextMarker?: string }>((resolve, reject) => this.#client.getBucket({ Bucket: this.config.bucket, Region: this.config.region, Prefix: prefix, ...(marker ? { Marker: marker } : {}) }, (error, result) => error ? reject(new Error("Tencent COS list failed", { cause: error })) : resolve(result ?? {})));
      for (const item of data.Contents ?? []) if (typeof item.Key === "string") keys.push(item.Key);
      if (!data.IsTruncated) break;
      marker = data.NextMarker ?? keys.at(-1);
      if (!marker) break;
    }
    return keys;
  }

  /** List object keys with their last-modified timestamps (for TTL sweeps). */
  async listWithTimestamps(prefix: string): Promise<readonly { objectKey: string; lastModifiedMs: number }[]> {
    const items: { objectKey: string; lastModifiedMs: number }[] = [];
    let marker: string | undefined;
    for (let page = 0; page < 1000; page += 1) {
      const data = await new Promise<{ Contents?: Array<{ Key?: string; LastModified?: string }>; IsTruncated?: boolean; NextMarker?: string }>((resolve, reject) => this.#client.getBucket({ Bucket: this.config.bucket, Region: this.config.region, Prefix: prefix, ...(marker ? { Marker: marker } : {}) }, (error, result) => error ? reject(new Error("Tencent COS list failed", { cause: error })) : resolve(result ?? {})));
      for (const item of data.Contents ?? []) {
        if (typeof item.Key !== "string") continue;
        const lastModified = item.LastModified ? Date.parse(item.LastModified) : NaN;
        if (Number.isFinite(lastModified)) items.push({ objectKey: item.Key, lastModifiedMs: lastModified });
      }
      if (!data.IsTruncated) break;
      marker = data.NextMarker ?? items.at(-1)?.objectKey;
      if (!marker) break;
    }
    return items;
  }
}

/**
 * Tencent COS rejects custom metadata header names containing characters
 * outside `[a-z0-9-]` (for example underscores) with SignatureDoesNotMatch.
 * Normalize keys to lowercase hyphenated names, so `job_id` -> `job-id`.
 */
export function sanitizeMetadataKey(key: string): string {
  const normalized = key.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
  return normalized || "meta";
}
function encodeKey(key: string): string { return key.split("/").map(encodeURIComponent).join("/"); }
