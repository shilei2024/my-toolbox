import { NextRequest, NextResponse } from "next/server";
import { logoutUrl } from "@/server/auth-links";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  const returnTo = request.nextUrl.searchParams.get("next") ?? undefined;
  const target = logoutUrl(returnTo);
  if (!target) return NextResponse.redirect(new URL("/gallery", request.url));
  return NextResponse.redirect(target, 307);
}
