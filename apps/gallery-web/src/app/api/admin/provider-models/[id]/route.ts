import { proxyGalleryRequest } from "@/server/route-proxy";

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  return proxyGalleryRequest(request, `/v1/admin/provider-models/${encodeURIComponent(id)}`, "PATCH");
}
