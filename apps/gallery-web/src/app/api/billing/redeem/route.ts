import { proxyGalleryRequest } from "@/server/route-proxy";

export async function POST(request: Request) {
  return proxyGalleryRequest(request, "/v1/billing/redeem", "POST");
}
