import type { Metadata } from "next";
import { CollectionGrid } from "@/components/collection-grid";
import type { GalleryImageSummary } from "@/lib/gallery-types";
import { GalleryClientError, getFavorites } from "@/server/gallery-client";
import { resolveViewerFromRequest } from "@/server/viewer";

export const metadata: Metadata = { title: "收藏", robots: { index: false, follow: false } };
export default async function FavoritesPage() {
  const viewer = await resolveViewerFromRequest();
  let failed = false;
  let items: readonly GalleryImageSummary[] = [];
  let message = viewer.role === "guest" ? "请先登录后查看收藏。" : "收藏公开作品后，可以在这里快速找到它们。";
  if (viewer.role !== "guest") try { items = (await getFavorites({ limit: 48 }, viewer)).items; } catch (error) { failed = true; message = error instanceof GalleryClientError ? error.message : "暂时无法读取收藏。"; }
  return <main className="page-shell"><section className="collection-head"><p className="eyebrow"><span className="eyebrow-dot" />Saved works</p><h1 className="collection-title">收藏</h1><p className="collection-copy">收藏的作品都在这里。</p></section><CollectionGrid initialItems={items} authenticated={viewer.role !== "guest"} error={failed ? message : undefined} loginHref="/login?next=/favorites" emptyTitle={viewer.role === "guest" ? "登录后查看收藏" : "收藏夹还是空的"} emptyCopy={message} removeWhenUnfavorited /></main>;
}
