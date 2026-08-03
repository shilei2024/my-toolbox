import { createReadStream } from "node:fs";
import { mkdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import type { ProviderImageOutput } from "../providers/types.ts";
import type { StorageProvider, StoredAsset } from "../storage/storage-provider.ts";

export interface PersistedImageAsset extends StoredAsset {
  readonly mimeType: string;
  readonly byteSize: number;
  readonly width: number;
  readonly height: number;
  readonly sha256: string;
}

export class ImagePersistenceService {
  readonly #root: string;
  readonly #storage: StorageProvider;
  readonly #fetcher: typeof fetch;
  readonly #remoteDownloadTimeoutMs: number;
  constructor(storage: StorageProvider, temporaryRoot: string, remoteDownloadTimeoutMs: number, fetcher: typeof fetch = fetch) { this.#storage = storage; this.#root = path.resolve(temporaryRoot); this.#remoteDownloadTimeoutMs = remoteDownloadTimeoutMs; this.#fetcher = fetcher; }
  async persist(jobId: string, outputs: readonly ProviderImageOutput[]): Promise<readonly PersistedImageAsset[]> {
    const assets: PersistedImageAsset[] = [];
    try {
      const safeJobId = objectKeySegment(jobId);
      for (const [index, output] of outputs.entries()) {
        const local = await this.materialize(output);
        try {
          const info = await stat(local);
          const extension = extensionFor(output.mimeType);
          const key = `images/jobs/${safeJobId}/${index}${extension}`;
          const sha256 = await digestFile(local);
          const stored = await this.#storage.upload({ objectKey: key, body: createReadStream(local), contentType: output.mimeType, contentLength: info.size, metadata: { job_id: jobId, output_index: String(index) } });
          assets.push({ ...stored, mimeType: output.mimeType, byteSize: info.size, width: output.width, height: output.height, sha256 });
        } finally { await rm(local, { force: true }); }
      }
      return assets;
    } catch (error) {
      await Promise.allSettled(assets.map((asset) => this.#storage.delete(asset.objectKey)));
      throw error;
    }
  }
  private async materialize(output: ProviderImageOutput): Promise<string> {
    await mkdir(this.#root, { recursive: true });
    if (output.kind === "local-file") { const local = path.resolve(output.path); if (!isWithin(this.#root, local)) throw new Error("Provider output is outside the configured temporary directory"); return local; }
    const target = path.join(this.#root, `${randomUUID()}${extensionFor(output.mimeType)}`);
    if (output.kind === "base64") { await writeFile(target, Buffer.from(output.data, "base64")); return target; }
    const source = new URL(output.url);
    if (source.protocol !== "https:") throw new Error("Provider output URL must use HTTPS");
    const response = await this.#fetcher(source, { signal: AbortSignal.timeout(this.#remoteDownloadTimeoutMs) });
    if (!response.ok) throw new Error("Provider output download failed");
    await writeFile(target, Buffer.from(await response.arrayBuffer()));
    return target;
  }
}
function isWithin(root: string, candidate: string): boolean { const relative = path.relative(root, candidate); return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative); }
function extensionFor(mimeType: string): string { return mimeType === "image/jpeg" ? ".jpg" : mimeType === "image/webp" ? ".webp" : ".png"; }
function objectKeySegment(value: string): string { if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(value)) throw new Error("Generation job id is invalid"); return value; }
async function digestFile(filename: string): Promise<string> {
  const digest = createHash("sha256");
  for await (const chunk of createReadStream(filename)) digest.update(chunk as Buffer);
  return digest.digest("hex");
}
