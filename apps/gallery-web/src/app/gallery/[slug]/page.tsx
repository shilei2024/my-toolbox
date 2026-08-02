/* eslint-disable @next/next/no-img-element */
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArtworkActions } from "@/components/artwork-actions";
import type { GalleryImageDetail } from "@/lib/gallery-types";
import { buildArtworkJsonLd, buildArtworkSeo, serializeJsonLd } from "@/lib/seo";
import { GalleryClientError, getGalleryDetail } from "@/server/gallery-client";
import { getPublicSeoDetail } from "@/server/seo-client";
import { resolveViewerFromRequest } from "@/server/viewer";

interface DetailPageProps {
  readonly params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: DetailPageProps): Promise<Metadata> {
  const { slug } = await params;
  try {
    const image = await getPublicSeoDetail(slug);
    const seo = buildArtworkSeo(image);
    return {
      title: seo.title,
      description: seo.description,
      alternates: { canonical: seo.canonicalUrl },
      openGraph: {
        type: "article",
        locale: "zh_CN",
        url: seo.canonicalUrl,
        title: seo.title,
        description: seo.description,
        publishedTime: image.publishedAt,
        images: [{ url: seo.imageUrl, width: image.asset.width, height: image.asset.height, alt: seo.title }],
      },
      twitter: { card: "summary_large_image", title: seo.title, description: seo.description, images: [seo.imageUrl] },
      robots: { index: true, follow: true, googleBot: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1 } },
    };
  } catch {
    return { title: "作品详情", robots: { index: false, follow: false } };
  }
}

export default async function GalleryDetailPage({ params }: DetailPageProps) {
  const { slug } = await params;
  const viewer = await resolveViewerFromRequest();
  let image: GalleryImageDetail;
  try {
    image = await getGalleryDetail(slug, viewer);
  } catch (error) {
    if (error instanceof GalleryClientError && error.status === 404) notFound();
    return <ServiceError error={error} />;
  }

  const publicImage = viewer.role === "guest" ? image : await publicDetailOrUndefined(slug);
  return (
    <main className="page-shell">
      {publicImage && <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializeJsonLd(buildArtworkJsonLd(publicImage)) }} />}
      <nav className="breadcrumb" aria-label="面包屑导航">
        <Link href="/gallery">作品库</Link><span aria-hidden="true">/</span><span aria-current="page">{image.title || "未命名作品"}</span>
      </nav>
      <div className="detail-shell">
        <div className="detail-art real-detail-art"><img src={image.asset.url} width={image.asset.width} height={image.asset.height} alt={image.title || "AI 生成作品"} /></div>
        <aside className="detail-panel">
          <p className="eyebrow"><span className="eyebrow-dot" />Artwork detail</p>
          <h1>{image.title || "未命名作品"}</h1>
          {image.description && <p className="detail-description">{image.description}</p>}
          <dl className="metadata-list">
            <MetadataRow label="创作者" value={image.creator?.displayName || "未设置公开名称"} />
            <MetadataRow label="工作流" value={image.workflowName} />
            <MetadataRow label="生成模型" value={image.model || image.providerCode} />
            <MetadataRow label="图片尺寸" value={`${image.width} × ${image.height}`} />
            <MetadataRow label="创建时间" value={formatDate(image.createdAt)} />
            {image.seed && <MetadataRow label="Seed" value={image.seed} />}
            {image.sampler && <MetadataRow label="采样器" value={image.sampler} />}
            {image.steps !== undefined && <MetadataRow label="Steps" value={String(image.steps)} />}
          </dl>
          {image.tags.length > 0 && <div className="tag-list" aria-label="作品标签">{image.tags.map((tag) => <Link key={tag} href={`/gallery?tag=${encodeURIComponent(tag)}`}>{tag}</Link>)}</div>}
          {image.prompt ? <section className="prompt-panel"><strong>提示词</strong><p>{image.prompt}</p>{image.negativePrompt && <><strong>负面提示词</strong><p>{image.negativePrompt}</p></>}</section> : <div className="privacy-note">创作者已隐藏提示词。只有作品拥有者和管理员可以查看。</div>}
          <ArtworkActions imageId={image.id} initialLiked={image.viewerHasLiked} initialFavorited={image.viewerHasFavorited} initialLikeCount={image.likeCount} initialFavoriteCount={image.favoriteCount} authenticated={viewer.role !== "guest"} canDelete={image.canDelete} />
        </aside>
      </div>
    </main>
  );
}

async function publicDetailOrUndefined(slug: string): Promise<GalleryImageDetail | undefined> {
  try { return await getPublicSeoDetail(slug); } catch { return undefined; }
}

function ServiceError({ error }: { readonly error: unknown }) {
  return <main className="page-shell"><section className="state-stage error-state"><div className="state-message"><div className="state-mark">!</div><h1>暂时无法读取作品</h1><p>{error instanceof GalleryClientError ? error.message : "Gallery 服务暂不可用"}</p><Link className="button" href="/gallery" style={{ marginTop: 18 }}>返回作品库</Link></div></section></main>;
}

function MetadataRow({ label, value }: { readonly label: string; readonly value: string }) {
  return <div className="metadata-row"><dt>{label}</dt><dd>{value}</dd></div>;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai" }).format(new Date(value));
}
