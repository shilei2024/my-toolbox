export type GalleryErrorCode =
  | "invalid_request"
  | "invalid_cursor"
  | "authentication_required"
  | "forbidden"
  | "image_not_found"
  | "resource_not_found"
  | "conflict"
  | "service_unavailable"
  | "internal_error";

export class GalleryError extends Error {
  readonly code: GalleryErrorCode;
  readonly statusCode: number;

  constructor(code: GalleryErrorCode, message: string, statusCode: number, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "GalleryError";
    this.code = code;
    this.statusCode = statusCode;
  }
}

export function normalizeGalleryError(error: unknown): GalleryError {
  if (error instanceof GalleryError) return error;
  return new GalleryError("internal_error", "The Gallery request could not be completed", 500, error);
}
