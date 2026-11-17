import type { Metadata } from "next";
import { CollectionGrid } from "@/components/collection-grid";
import type { GalleryImageSummary } from "@/lib/gallery-types";
import { GalleryClientError, getMyImages } from "@/server/gallery-client";
import { resolveViewerFromRequest } from "@/server/viewer";

export const metadata: Metadata = { title: "我的作品", robots: { index: false, follow: false } };
export default async function MyImagesPage() {
  const viewer = await resolveViewerFromRequest();
  let failed = false;
  let items: readonly GalleryImageSummary[] = [];
  let message = viewer.role === "guest" ? "请先登录后查看个人作品。" : "你生成的图片会出现在这里。";
  if (viewer.role !== "guest") try { items = (await getMyImages({ limit: 48 }, viewer)).items; } catch (error) { failed = true; message = error instanceof GalleryClientError ? error.message : "暂时无法读取个人作品。"; }
  return <main className="page-shell"><section className="collection-head"><p className="eyebrow"><span className="eyebrow-dot" />Personal library</p><h1 className="collection-title">我的作品</h1><p className="collection-copy">管理你的图片与视频。</p></section><CollectionGrid initialItems={items} authenticated={viewer.role !== "guest"} error={failed ? message : undefined} loginHref="/login?next=/my-images" emptyTitle={viewer.role === "guest" ? "登录后查看个人作品" : "还没有个人作品"} emptyCopy={message} /></main>;
}
