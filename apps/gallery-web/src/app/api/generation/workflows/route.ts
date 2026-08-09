import { proxyGenerationRequest } from "@/server/generation-proxy";

export const dynamic = "force-dynamic";
export function GET(request: Request) {
  const query = new URL(request.url).search;
  return proxyGenerationRequest(request, `/v1/generation/workflows${query}`, "GET");
}
