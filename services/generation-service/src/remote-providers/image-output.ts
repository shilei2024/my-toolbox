import sharp, { type Metadata } from "sharp";
import { ProviderError } from "../providers/errors.ts";
import type { ProviderImageOutput } from "../providers/types.ts";

export async function base64ImageOutput(providerCode: string, data: string, maxDecodedBytes: number): Promise<ProviderImageOutput> {
  if (!data || !/^[a-zA-Z0-9+/]+={0,2}$/.test(data)) throw invalid(providerCode, "invalid_base64", "Provider returned invalid image data");
  const buffer = Buffer.from(data, "base64");
  if (buffer.byteLength === 0 || buffer.byteLength > maxDecodedBytes) throw invalid(providerCode, "invalid_image_size", "Provider returned an invalid image payload size");
  let metadata: Metadata;
  try { metadata = await sharp(buffer).metadata(); }
  catch (error) { throw new ProviderError({ providerCode, category: "upstream", code: "invalid_image", message: "Provider returned an unreadable image", retryable: false, cause: error }); }
  const width = metadata.width;
  const height = metadata.height;
  if (!width || !height) throw invalid(providerCode, "invalid_image_dimensions", "Provider returned invalid image dimensions");
  const mimeType = metadata.format === "jpeg" ? "image/jpeg" : metadata.format === "webp" ? "image/webp" : metadata.format === "png" ? "image/png" : undefined;
  if (!mimeType) throw invalid(providerCode, "unsupported_image_format", "Provider returned an unsupported image format");
  return { kind: "base64", data, mimeType, width, height };
}

export function combinedPrompt(prompt: string, negativePrompt: string): string {
  const negative = negativePrompt.trim();
  return negative ? `${prompt}\n\nAvoid: ${negative}` : prompt;
}

function invalid(providerCode: string, code: string, message: string): ProviderError {
  return new ProviderError({ providerCode, category: "upstream", code, message, retryable: false });
}
