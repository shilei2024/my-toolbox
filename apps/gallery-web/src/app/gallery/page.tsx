import type { Metadata } from "next";
import { GalleryExplorer } from "@/components/gallery-explorer";
import type { GalleryPageData, GalleryQuery } from "@/lib/gallery-types";
import { buildGalleryJsonLd, serializeJsonLd } from "@/lib/seo";
import { GalleryClientError, getPublicGallery } from "@/server/gallery-client";
import { resolveViewerFromRequest } from "@/server/viewer";

const GALLERY_DESCRIPTION = "浏览公开且通过审核的 AI 图像作品，发现不同工作流、构图与创作风格。";

export async function generateMetadata({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }): Promise<Metadata> {
  const params = await searchParams;
  const filtered = ["q", "tag", "workflow", "orientation", "cursor"].some((key) => params[key] !== undefined);
  return {
    title: "发现 AI 图像作品",
    description: GALLERY_DESCRIPTION,
    alternates: { canonical: "/gallery" },
    robots: filtered ? { index: false, follow: true } : undefined,
    openGraph: { title: "发现 AI 图像作品", description: GALLERY_DESCRIPTION, url: "/gallery", type: "website" },
    twitter: { card: "summary_large_image", title: "发现 AI 图像作品", description: GALLERY_DESCRIPTION },
  };
}

export default async function GalleryPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const viewer = await resolveViewerFromRequest();
  const query: GalleryQuery = {
    ...(single(params.q) ? { q: single(params.q) } : {}),
    ...(single(params.tag) ? { tag: single(params.tag) } : {}),
    ...(single(params.workflow) ? { workflow: single(params.workflow) } : {}),
    ...(orientation(params.orientation) ? { orientation: orientation(params.orientation) } : {}),
  };
  let initialPage: GalleryPageData = { items: [] };
  let initialError: string | undefined;
  try { initialPage = await getPublicGallery(query, viewer); }
  catch (error) { initialError = error instanceof GalleryClientError ? error.message : "Gallery 服务暂不可用"; }

  return <main className="page-shell"><script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializeJsonLd(buildGalleryJsonLd()) }} /><section className="gallery-hero"><div><p className="eyebrow"><span className="eyebrow-dot" />Curated AI works</p><h1 className="hero-title">让好作品，<span>安静地被看见。</span></h1><p className="hero-copy">浏览公开且通过审核的 AI 作品。隐藏提示词只对作品拥有者和管理员可见。</p></div></section><GalleryExplorer initialPage={initialPage} initialError={initialError} authenticated={viewer.role !== "guest"} /></main>;
}

function single(value: string | string[] | undefined): string | undefined { return typeof value === "string" ? value : undefined; }
function orientation(value: string | string[] | undefined): GalleryQuery["orientation"] { const result = single(value); return result === "portrait" || result === "square" || result === "landscape" ? result : undefined; }
