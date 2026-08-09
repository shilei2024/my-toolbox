import { proxyTaskRequest } from "@/server/task-proxy";

export function GET(request: Request) { return proxyTaskRequest(request); }
