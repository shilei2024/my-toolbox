import { proxyGalleryRequest } from "@/server/route-proxy";

export async function GET(request: Request, context: { params: Promise<{ slug: string }> }) {
  const { slug } = await context.params;
  return proxyGalleryRequest(request, `/v1/gallery/${encodeURIComponent(slug)}`);
}
