import { resolveViewerFromRequest } from "@/server/viewer";

export const dynamic = "force-dynamic";

export async function GET() {
  const viewer = await resolveViewerFromRequest();
  return Response.json({
    role: viewer.role,
    bridge: viewer.bridge ?? "unconfigured",
    ...(viewer.userId ? { userId: viewer.userId } : {}),
    ...(viewer.email ? { email: viewer.email } : {}),
  }, {
    headers: { "Cache-Control": "no-store" },
  });
}
