import "server-only";

import { randomUUID } from "node:crypto";
import { cache } from "react";
import type { GalleryImageDetail, SeoImageEntry, ViewerContext } from "@/lib/gallery-types";
import { getGalleryDetail, serviceRequest } from "./gallery-client";

interface SeoImagePage {
  readonly items: readonly SeoImageEntry[];
  readonly nextCursor?: string;
}

export const getPublicSeoDetail = cache(async (slug: string): Promise<GalleryImageDetail> => {
  return getGalleryDetail(slug, seoViewer());
});

export async function getSitemapImages(maxEntries = 50_000): Promise<readonly SeoImageEntry[]> {
  const items: SeoImageEntry[] = [];
  let cursor: string | undefined;
  const seen = new Set<string>();
  while (items.length < maxEntries) {
    const params = new URLSearchParams({ limit: String(Math.min(1_000, maxEntries - items.length)) });
    if (cursor) params.set("cursor", cursor);
    const page = await serviceRequest<SeoImagePage>(`/v1/seo/images?${params}`, seoViewer());
    items.push(...page.items);
    if (!page.nextCursor || seen.has(page.nextCursor)) break;
    seen.add(page.nextCursor);
    cursor = page.nextCursor;
  }
  return items;
}

function seoViewer(): ViewerContext {
  return { role: "guest", requestId: randomUUID() };
}
