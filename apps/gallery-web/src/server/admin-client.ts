import "server-only";

import type { AdminDashboard } from "@/lib/admin-types";
import type { ViewerContext } from "@/lib/gallery-types";
import { serviceRequest } from "./gallery-client";

export async function getAdminDashboard(viewer: ViewerContext): Promise<AdminDashboard> {
  return serviceRequest<AdminDashboard>("/v1/admin/dashboard", viewer);
}
