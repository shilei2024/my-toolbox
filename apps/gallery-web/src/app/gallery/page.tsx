import type { Metadata } from "next";
import { ShowcaseGallery } from "@/components/showcase-gallery";
import { publicAdminConsoleUrl } from "@/lib/admin-links";
import type { GalleryFacets, GalleryPageData, GalleryQuery } from "@/lib/gallery-types";
import { buildGalleryJsonLd, serializeJsonLd } from "@/lib/seo";
import { mainSiteUrl } from "@/lib/site-links";
import { GalleryClientError, getGalleryFacets, getPublicGallery } from "@/server/gallery-client";
import { resolveViewerFromRequest } from "@/server/viewer";

const GALLERY_DESCRIPTION = "浏览公开且通过审核的 AI 图像与视频作品，每件作品都附完整提示词，可一键复制用于创作。";

const EMPTY_FACETS: GalleryFacets = { total: 0, media: { image: 0, video: 0 }, workflows: [] };

export async function generateMetadata({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }): Promise<Metadata> {
  const params = await searchParams;
  const filtered = ["q", "tag", "workflow", "orientation", "mediaType", "cursor", "sort"].some((key) => params[key] !== undefined);
  return {
    title: "灵感画廊 · 每件作品都附完整提示词",
    description: GALLERY_DESCRIPTION,
    alternates: { canonical: "/gallery" },
    robots: filtered ? { index: false, follow: true } : undefined,
    openGraph: { title: "灵感画廊 · 每件作品都附完整提示词", description: GALLERY_DESCRIPTION, url: "/gallery", type: "website" },
    twitter: { card: "summary_large_image", title: "灵感画廊 · 每件作品都附完整提示词", description: GALLERY_DESCRIPTION },
  };
}

export default async function GalleryPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const viewer = await resolveViewerFromRequest();
  const mediaType = single(params.mediaType);
  const sort = single(params.sort);
  const query: GalleryQuery = {
    ...(single(params.q) ? { q: single(params.q)! } : {}),
    ...(single(params.tag) ? { tag: single(params.tag)! } : {}),
    ...(single(params.workflow) ? { workflow: single(params.workflow)! } : {}),
    ...(orientation(params.orientation) ? { orientation: orientation(params.orientation)! } : {}),
    ...(mediaType === "image" || mediaType === "video" ? { mediaType } : {}),
    ...(sort === "popular" || sort === "latest" ? { sort } : {}),
  };

  const [pageResult, facetsResult] = await Promise.allSettled([getPublicGallery(query, viewer), getGalleryFacets(viewer)]);
  let initialPage: GalleryPageData = { items: [] };
  let initialError: string | undefined;
  if (pageResult.status === "fulfilled") initialPage = pageResult.value;
  else initialError = pageResult.reason instanceof GalleryClientError ? pageResult.reason.message : "Gallery 服务暂不可用";
  const initialFacets = facetsResult.status === "fulfilled" ? facetsResult.value : EMPTY_FACETS;

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializeJsonLd(buildGalleryJsonLd()) }} />
      <ShowcaseGallery
        initialPage={initialPage}
        initialFacets={initialFacets}
        {...(initialError ? { initialError } : {})}
        viewer={{
          role: viewer.role,
          ...(viewer.nickname || viewer.email ? { displayName: viewer.nickname || viewer.email } : {}),
        }}
        links={{
          login: `/login?next=${encodeURIComponent("/gallery")}`,
          create: "/create",
          ...(viewer.role === "admin" ? { admin: publicAdminConsoleUrl() } : {}),
          ...(mainSiteUrl() ? { mainSite: mainSiteUrl() } : {}),
        }}
        initialFilters={{
          ...(query.q ? { query: query.q } : {}),
          ...(query.mediaType ? { mediaType: query.mediaType } : {}),
          ...(query.workflow ? { model: query.workflow } : {}),
          ...(query.orientation ? { orientation: query.orientation } : {}),
          ...(query.sort ? { sort: query.sort } : {}),
        }}
      />
    </>
  );
}

function single(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
}

function orientation(value: string | string[] | undefined): GalleryQuery["orientation"] {
  const result = single(value);
  return result === "portrait" || result === "square" || result === "landscape" ? result : undefined;
}
