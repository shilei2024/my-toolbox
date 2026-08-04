import { proxyGalleryRequest } from "@/server/route-proxy";
export async function DELETE(request: Request, context: { params: Promise<{ id: string }> }) { const { id } = await context.params; return proxyGalleryRequest(request, `/v1/images/${encodeURIComponent(id)}`, "DELETE"); }
