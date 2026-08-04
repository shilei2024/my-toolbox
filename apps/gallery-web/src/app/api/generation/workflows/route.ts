import { proxyGenerationRequest } from "@/server/generation-proxy";

export const dynamic = "force-dynamic";
export function GET(request: Request) { return proxyGenerationRequest(request, "/v1/generation/workflows", "GET"); }
