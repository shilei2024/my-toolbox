import { createHmac, timingSafeEqual } from "node:crypto";
import { GalleryError } from "./errors.ts";

interface CursorPayload {
  readonly v: 1;
  readonly scope: string;
  readonly at: string;
  readonly id: string;
}

export interface DecodedCursor {
  readonly at: string;
  readonly id: string;
}

export class GalleryCursorCodec {
  readonly #secret: Buffer;

  constructor(secret: string) {
    if (Buffer.byteLength(secret, "utf8") < 32) throw new Error("Gallery cursor secret must contain at least 32 bytes");
    this.#secret = Buffer.from(secret, "utf8");
  }

  encode(scope: string, cursor: DecodedCursor): string {
    assertScope(scope);
    assertCursor(cursor);
    const body = Buffer.from(JSON.stringify({ v: 1, scope, ...cursor } satisfies CursorPayload)).toString("base64url");
    return `${body}.${this.sign(body)}`;
  }

  decode(scope: string, token?: string): DecodedCursor | undefined {
    if (!token) return undefined;
    assertScope(scope);
    const parts = token.split(".");
    const body = parts[0];
    const signature = parts[1];
    if (parts.length !== 2 || !body || !signature || !this.validSignature(body, signature)) throw invalidCursor();
    try {
      const parsed = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as unknown;
      if (!isCursorPayload(parsed) || parsed.scope !== scope) throw invalidCursor();
      assertCursor(parsed);
      return { at: parsed.at, id: parsed.id };
    } catch (error) {
      if (error instanceof GalleryError) throw error;
      throw invalidCursor();
    }
  }

  private sign(body: string): string {
    return createHmac("sha256", this.#secret).update(body).digest("base64url");
  }

  private validSignature(body: string, supplied: string): boolean {
    const expected = Buffer.from(this.sign(body));
    const actual = Buffer.from(supplied);
    return expected.length === actual.length && timingSafeEqual(expected, actual);
  }
}

function isCursorPayload(value: unknown): value is CursorPayload {
  return !!value && typeof value === "object" && !Array.isArray(value)
    && (value as Partial<CursorPayload>).v === 1
    && typeof (value as Partial<CursorPayload>).scope === "string"
    && typeof (value as Partial<CursorPayload>).at === "string"
    && typeof (value as Partial<CursorPayload>).id === "string";
}

function assertCursor(cursor: DecodedCursor): void {
  if (!Number.isFinite(Date.parse(cursor.at)) || !/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(cursor.id)) throw invalidCursor();
}

function assertScope(scope: string): void {
  if (!/^[a-z][a-z0-9:_-]{0,63}$/.test(scope)) throw new Error("Gallery cursor scope is invalid");
}

function invalidCursor(): GalleryError {
  return new GalleryError("invalid_cursor", "The pagination cursor is invalid", 400);
}
