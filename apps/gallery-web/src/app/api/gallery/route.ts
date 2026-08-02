import { proxyGalleryRequest } from "@/server/route-proxy";

export async function GET(request: Request) {
  const url = new URL(request.url);
  return proxyGalleryRequest(request, `/v1/gallery${url.search}`);
}
