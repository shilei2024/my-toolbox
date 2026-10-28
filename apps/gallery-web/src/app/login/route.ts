import { NextRequest, NextResponse } from "next/server";
import { loginUrl } from "@/server/auth-links";

export const dynamic = "force-dynamic";

function absoluteReturnTo(request: NextRequest, next?: string): string | undefined {
  if (!next) return undefined;
  if (next.startsWith("http://") || next.startsWith("https://")) return next;
  if (next.startsWith("/") && !next.startsWith("//")) {
    const base = process.env.GALLERY_PUBLIC_ORIGIN?.trim() || new URL(request.url).origin;
    return `${base}${next}`;
  }
  return undefined;
}

export function GET(request: NextRequest) {
  const raw = request.nextUrl.searchParams.get("next") ?? undefined;
  const target = loginUrl(absoluteReturnTo(request, raw));
  if (!target) return NextResponse.redirect(new URL("/gallery", request.url));
  return NextResponse.redirect(target, 307);
}
