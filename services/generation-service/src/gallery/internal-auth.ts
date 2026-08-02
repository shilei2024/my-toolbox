import { createHmac, randomUUID, timingSafeEqual } from "node:crypto";
import { GalleryError } from "./errors.ts";
import type { ViewerContext, ViewerRole } from "./types.ts";

export const USER_CONTEXT_HEADER = "x-mavis-user-context";
export const USER_CONTEXT_SIGNATURE_HEADER = "x-mavis-user-signature";

interface SignedViewerPayload {
  readonly v: 1;
  readonly role: ViewerRole;
  readonly userId?: number;
  readonly requestId: string;
  readonly issuedAt: number;
  readonly expiresAt: number;
}

export class InternalViewerContextCodec {
  readonly #secret: Buffer;
  readonly #maxLifetimeSeconds: number;
  readonly #clock: () => number;

  constructor(secret: string, maxLifetimeSeconds = 300, clock: () => number = () => Math.floor(Date.now() / 1000)) {
    if (Buffer.byteLength(secret, "utf8") < 32) throw new Error("Internal user context secret must contain at least 32 bytes");
    this.#secret = Buffer.from(secret, "utf8");
    this.#maxLifetimeSeconds = maxLifetimeSeconds;
    this.#clock = clock;
  }

  issue(viewer: { readonly role: ViewerRole; readonly userId?: number; readonly requestId?: string }, lifetimeSeconds = 60): { readonly context: string; readonly signature: string } {
    if (!Number.isInteger(lifetimeSeconds) || lifetimeSeconds < 1 || lifetimeSeconds > this.#maxLifetimeSeconds) throw new Error("Internal user context lifetime is invalid");
    validateIdentity(viewer.role, viewer.userId);
    const now = this.#clock();
    const payload: SignedViewerPayload = {
      v: 1,
      role: viewer.role,
      ...(viewer.userId ? { userId: viewer.userId } : {}),
      requestId: viewer.requestId ?? randomUUID(),
      issuedAt: now,
      expiresAt: now + lifetimeSeconds,
    };
    const context = Buffer.from(JSON.stringify(payload)).toString("base64url");
    return { context, signature: this.sign(context) };
  }

  verify(headers: Readonly<Record<string, string | string[] | undefined>>): ViewerContext {
    const context = scalarHeader(headers[USER_CONTEXT_HEADER]);
    const signature = scalarHeader(headers[USER_CONTEXT_SIGNATURE_HEADER]);
    if (!context || !signature || !this.validSignature(context, signature)) throw unauthorized();
    try {
      const value = JSON.parse(Buffer.from(context, "base64url").toString("utf8")) as unknown;
      if (!isPayload(value)) throw unauthorized();
      const now = this.#clock();
      if (value.issuedAt > now + 5 || value.expiresAt < now || value.expiresAt - value.issuedAt > this.#maxLifetimeSeconds) throw unauthorized();
      validateIdentity(value.role, value.userId);
      return { role: value.role, requestId: value.requestId, ...(value.userId ? { userId: value.userId } : {}) };
    } catch (error) {
      if (error instanceof GalleryError) throw error;
      throw unauthorized();
    }
  }

  private sign(value: string): string { return createHmac("sha256", this.#secret).update(value).digest("base64url"); }
  private validSignature(context: string, signature: string): boolean {
    const expected = Buffer.from(this.sign(context));
    const actual = Buffer.from(signature);
    return expected.length === actual.length && timingSafeEqual(expected, actual);
  }
}

function isPayload(value: unknown): value is SignedViewerPayload {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Partial<SignedViewerPayload>;
  return item.v === 1
    && new Set(["guest", "user", "admin"]).has(item.role ?? "")
    && typeof item.requestId === "string" && /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(item.requestId)
    && Number.isInteger(item.issuedAt) && Number.isInteger(item.expiresAt);
}

function validateIdentity(role: ViewerRole, userId?: number): void {
  const hasUser = Number.isInteger(userId) && (userId ?? 0) > 0;
  if ((role === "guest" && userId !== undefined) || (role !== "guest" && !hasUser)) throw unauthorized();
}

function scalarHeader(value: string | string[] | undefined): string | undefined { return Array.isArray(value) ? undefined : value; }
function unauthorized(): GalleryError { return new GalleryError("authentication_required", "Valid internal authentication is required", 401); }
