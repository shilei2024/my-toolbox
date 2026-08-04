import { proxyGenerationRequest } from "@/server/generation-proxy";

export function POST(request: Request) { return proxyGenerationRequest(request, "/v1/generations", "POST"); }
