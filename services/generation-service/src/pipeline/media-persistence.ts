import { createHash, randomUUID } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import { mkdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { ProviderImageOutput, ProviderOutput, ProviderVideoOutput } from "../providers/types.ts";
import type { StorageProvider, StoredAsset } from "../storage/storage-provider.ts";
import { ImagePersistenceService } from "./image-persistence.ts";

export interface PersistedGenerationAsset extends StoredAsset {
  /** Omitted by the legacy image persistence path and treated as image. */
  readonly mediaType?: "image" | "video";
  readonly mimeType: string;
  readonly byteSize: number;
  readonly width: number;
  readonly height: number;
  readonly sha256: string;
  readonly durationSeconds?: number;
}

export interface GenerationPersistence {
  persist(jobId: string, outputs: readonly ProviderOutput[], ownerKey?: string): Promise<readonly PersistedGenerationAsset[]>;
}

export class MediaPersistenceService implements GenerationPersistence {
  readonly #images: ImagePersistenceService;
  readonly #videos: VideoPersistenceService;

  constructor(images: ImagePersistenceService, videos: VideoPersistenceService) {
    this.#images = images;
    this.#videos = videos;
  }

  async persist(jobId: string, outputs: readonly ProviderOutput[], ownerKey?: string): Promise<readonly PersistedGenerationAsset[]> {
    if (outputs.length === 0) throw new Error("Provider returned no generation output");
    const mediaTypes = new Set(outputs.map((output) => output.mediaType ?? "image"));
    if (mediaTypes.size !== 1) throw new Error("Provider returned mixed media outputs");
    if (mediaTypes.has("video")) return this.#videos.persist(jobId, outputs as readonly ProviderVideoOutput[], ownerKey);
    const images = await this.#images.persist(jobId, outputs as readonly ProviderImageOutput[], ownerKey);
    return images.map((asset) => ({ ...asset, mediaType: "image" as const }));
  }
}

export class VideoPersistenceService {
  readonly #root: string;
  readonly #storage: StorageProvider;
  readonly #fetcher: typeof fetch;
  readonly #remoteDownloadTimeoutMs: number;
  readonly #maxBytes: number;

  constructor(storage: StorageProvider, temporaryRoot: string, remoteDownloadTimeoutMs: number, maxBytes: number, fetcher: typeof fetch = fetch) {
    this.#storage = storage;
    this.#root = path.resolve(temporaryRoot);
    this.#remoteDownloadTimeoutMs = remoteDownloadTimeoutMs;
    this.#maxBytes = maxBytes;
    this.#fetcher = fetcher;
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) throw new TypeError("Video max bytes must be a positive integer");
  }

  async persist(jobId: string, outputs: readonly ProviderVideoOutput[], ownerKey?: string): Promise<readonly PersistedGenerationAsset[]> {
    const assets: PersistedGenerationAsset[] = [];
    try {
      const safeJobId = objectKeySegment(jobId);
      for (const [index, output] of outputs.entries()) {
        validateVideoOutput(output);
        const local = await this.materialize(output);
        try {
          const info = await stat(local);
          if (info.size < 1 || info.size > this.#maxBytes) throw new Error("Video output exceeds the configured size limit");
          const key = `videos/${ownerKey ?? "jobs"}/${safeJobId}/${index}${extensionFor(output.mimeType)}`;
          const sha256 = await digestFile(local);
          const stored = await this.#storage.upload({ objectKey: key, body: createReadStream(local), contentType: output.mimeType, contentLength: info.size });
          assets.push({ ...stored, mediaType: "video", mimeType: output.mimeType, byteSize: info.size, width: output.width, height: output.height, durationSeconds: output.durationSeconds, sha256 });
        } finally { await rm(local, { force: true }); }
      }
      return assets;
    } catch (error) {
      await Promise.allSettled(assets.map((asset) => this.#storage.delete(asset.objectKey)));
      throw error;
    }
  }

  private async materialize(output: ProviderVideoOutput): Promise<string> {
    await mkdir(this.#root, { recursive: true });
    if (output.kind === "local-file") {
      const local = path.resolve(output.path);
      if (!isWithin(this.#root, local)) throw new Error("Provider output is outside the configured temporary directory");
      return local;
    }
    const target = path.join(this.#root, `${randomUUID()}${extensionFor(output.mimeType)}`);
    if (output.kind === "base64") {
      const data = Buffer.from(output.data, "base64");
      if (data.length < 1 || data.length > this.#maxBytes) throw new Error("Video output exceeds the configured size limit");
      await writeFile(target, data);
      return target;
    }
    const source = new URL(output.url);
    if (source.protocol !== "https:") throw new Error("Provider output URL must use HTTPS");
    const response = await this.#fetcher(source, { signal: AbortSignal.timeout(this.#remoteDownloadTimeoutMs) });
    if (!response.ok || !response.body) throw new Error("Provider output download failed");
    const declared = Number(response.headers.get("content-length"));
    if (Number.isFinite(declared) && declared > this.#maxBytes) throw new Error("Video output exceeds the configured size limit");
    let received = 0;
    const maxBytes = this.#maxBytes;
    const limiter = new Transform({
      transform(chunk: Buffer, _encoding, callback) {
        received += chunk.length;
        callback(received > maxBytes ? new Error("Video output exceeds the configured size limit") : undefined, chunk);
      },
    });
    try {
      await pipeline(Readable.fromWeb(response.body as never), limiter, createWriteStream(target, { flags: "wx" }));
      return target;
    } catch (error) {
      await rm(target, { force: true });
      throw error;
    }
  }
}

function validateVideoOutput(output: ProviderVideoOutput): void {
  if (!["video/mp4", "video/webm", "video/quicktime"].includes(output.mimeType)) throw new Error("Provider returned an unsupported video type");
  if (!Number.isSafeInteger(output.width) || output.width < 1 || !Number.isSafeInteger(output.height) || output.height < 1) throw new Error("Provider returned invalid video dimensions");
  if (!Number.isFinite(output.durationSeconds) || output.durationSeconds <= 0 || output.durationSeconds > 300) throw new Error("Provider returned an invalid video duration");
}

function extensionFor(mimeType: string): string { return mimeType === "video/webm" ? ".webm" : mimeType === "video/quicktime" ? ".mov" : ".mp4"; }
function objectKeySegment(value: string): string { if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(value)) throw new Error("Generation job id is invalid"); return value; }
function isWithin(root: string, candidate: string): boolean { const relative = path.relative(root, candidate); return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative); }
async function digestFile(filename: string): Promise<string> {
  const digest = createHash("sha256");
  for await (const chunk of createReadStream(filename)) digest.update(chunk as Buffer);
  return digest.digest("hex");
}
