import { proxyGalleryRequest } from "@/server/route-proxy";

export async function GET(request: Request) { return proxyGalleryRequest(request, "/v1/admin/dashboard"); }
