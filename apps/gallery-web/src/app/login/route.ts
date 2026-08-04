import { NextRequest, NextResponse } from "next/server";
import { loginUrl } from "@/server/auth-links";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  const next = request.nextUrl.searchParams.get("next") ?? undefined;
  const target = loginUrl(next);
  if (!target) return NextResponse.redirect(new URL("/gallery", request.url));
  return NextResponse.redirect(target, 307);
}
