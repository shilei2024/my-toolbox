import { proxyGenerationRequest } from "@/server/generation-proxy";

export async function GET(request: Request, context: RouteContext<"/api/generations/[id]">) {
  const { id } = await context.params;
  return proxyGenerationRequest(request, `/v1/generations/${encodeURIComponent(id)}`, "GET");
}

export async function DELETE(request: Request, context: RouteContext<"/api/generations/[id]">) {
  const { id } = await context.params;
  return proxyGenerationRequest(request, `/v1/generations/${encodeURIComponent(id)}`, "DELETE");
}
