import type { Readable } from "node:stream";
export interface StorageUpload { readonly objectKey: string; readonly body: Buffer | Readable; readonly contentType: string; readonly contentLength?: number; readonly metadata?: Readonly<Record<string, string>> }
export interface StoredAsset { readonly storageProvider: string; readonly bucket: string; readonly region: string; readonly objectKey: string; readonly url: string; readonly etag?: string }
export interface StorageProvider { readonly code: string; upload(input: StorageUpload): Promise<StoredAsset>; delete(objectKey: string): Promise<void> }

