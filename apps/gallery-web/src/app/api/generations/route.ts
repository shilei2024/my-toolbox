import { proxyGenerationRequest } from "@/server/generation-proxy";

export function GET(request: Request) { return proxyGenerationRequest(request, `/v1/generations${new URL(request.url).search}`, "GET"); }
export function POST(request: Request) { return proxyGenerationRequest(request, "/v1/generations", "POST"); }
