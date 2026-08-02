import COS from "cos-nodejs-sdk-v5";
import { GalleryError } from "./errors.ts";

export interface GalleryAssetRecord {
  readonly storageProvider: string;
  readonly bucket: string;
  readonly region: string;
  readonly objectKey: string;
  readonly publicUrl?: string;
}

export interface GalleryAssetUrlResolver {
  resolve(asset: GalleryAssetRecord, isPublic: boolean): Promise<string>;
}

interface CosSigningClient {
  getObjectUrl(options: Record<string, unknown>, callback: (error: Error | null, data?: { Url?: string }) => void): void;
}

export class TencentCosGalleryAssetUrlResolver implements GalleryAssetUrlResolver {
  readonly #client: CosSigningClient;
  readonly #allowedPublicHosts: ReadonlySet<string>;
  readonly #privateUrlTtlSeconds: number;

  constructor(options: {
    secretId: string;
    secretKey: string;
    securityToken?: string;
    allowedPublicHosts: readonly string[];
    privateUrlTtlSeconds: number;
    client?: CosSigningClient;
  }) {
    this.#allowedPublicHosts = new Set(options.allowedPublicHosts.map((host) => host.toLowerCase()));
    this.#privateUrlTtlSeconds = options.privateUrlTtlSeconds;
    this.#client = options.client ?? new COS({
      SecretId: options.secretId,
      SecretKey: options.secretKey,
      ...(options.securityToken ? { SecurityToken: options.securityToken } : {}),
    }) as unknown as CosSigningClient;
  }

  async resolve(asset: GalleryAssetRecord, isPublic: boolean): Promise<string> {
    if (asset.storageProvider !== "tencent_cos") throw new GalleryError("service_unavailable", "Image storage is unavailable", 503);
    if (isPublic && asset.publicUrl) return this.validatePublicUrl(asset.publicUrl);
    const url = await new Promise<string>((resolve, reject) => {
      this.#client.getObjectUrl({
        Bucket: asset.bucket,
        Region: asset.region,
        Key: asset.objectKey,
        Sign: true,
        Expires: this.#privateUrlTtlSeconds,
        Protocol: "https:",
      }, (error, data) => {
        if (error || !data?.Url) reject(new GalleryError("service_unavailable", "Image storage is unavailable", 503, error));
        else resolve(data.Url);
      });
    });
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") throw new GalleryError("service_unavailable", "Image storage returned an unsafe URL", 503);
    return parsed.toString();
  }

  private validatePublicUrl(value: string): string {
    let url: URL;
    try { url = new URL(value); } catch { throw new GalleryError("service_unavailable", "Image asset URL is invalid", 503); }
    if (url.protocol !== "https:" || !this.#allowedPublicHosts.has(url.hostname.toLowerCase())) throw new GalleryError("service_unavailable", "Image asset URL is not allowed", 503);
    url.username = "";
    url.password = "";
    return url.toString();
  }
}
