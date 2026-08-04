import "server-only";
import type { BillingSummary } from "@/lib/billing-types";
import type { ViewerContext } from "@/lib/gallery-types";
import { serviceRequest } from "./gallery-client";

export function getBillingSummary(viewer: ViewerContext): Promise<BillingSummary> {
  return serviceRequest<BillingSummary>("/v1/billing/summary", viewer);
}

