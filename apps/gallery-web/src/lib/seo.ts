/**
 * SEO 工具：公开来源地址解析 + 结构化数据（JSON-LD）构建。
 *
 * 只接受安全来源（HTTPS 或本机 loopback HTTP）；其他一律回退到配置的
 * 公开域名。任何 URL 都用公开来源拼接，避免开发机/内网地址泄漏到搜索引擎。
 * 序列化时绝不包含隐藏 Prompt、Provider 路由等私有字段。
 */

import type { GalleryImageDetail } from "./gallery-types";

/** 生产公开站点（环境变量未配置时的回退值）。 */
const FALLBACK_ORIGIN = "https://www.mindfulpenpal.com";

/**
 * 返回安全的公开站点来源（含协议与主机）。
 *
 * 可选参数 origin：传入时优先使用（仅当它是 HTTPS 或本机 loopback HTTP）；
 * 否则读取环境变量 GALLERY_PUBLIC_ORIGIN；两者都不安全/未配置时回退到
 * 生产域名。供 metadataBase / robots / sitemap / JSON-LD 使用。
 */
export function resolvePublicOrigin(origin?: string | URL): URL {
  const candidates = [origin ? String(origin).trim() : "", process.env.GALLERY_PUBLIC_ORIGIN?.trim() ?? ""];
  for (const candidate of candidates) {
    if (!candidate) continue;
    try {
      const parsed = new URL(candidate);
      if (parsed.protocol === "https:" || (parsed.protocol === "http:" && isLoopback(parsed.hostname))) {
        return parsed;
      }
    } catch {
      // try next candidate
    }
  }
  return new URL(FALLBACK_ORIGIN);
}

type JsonLd = Record<string, unknown>;

/** 画廊列表页（/gallery）的 CollectionPage 结构化数据。 */
export function buildGalleryJsonLd(): JsonLd {
  const origin = resolvePublicOrigin();
  return {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "Mavis Gallery",
    description: "浏览公开且通过审核的 AI 图像作品，发现不同工作流、构图与创作风格。",
    url: new URL("/gallery", origin).toString(),
    inLanguage: "zh-CN",
  };
}

/** 作品详情页的 CreativeWork 结构化数据（仅公开信息，不含隐藏 Prompt / Provider 路由）。 */
export function buildArtworkJsonLd(image: GalleryImageDetail): JsonLd {
  const origin = resolvePublicOrigin();
  const entry: JsonLd = {
    "@context": "https://schema.org",
    "@type": "CreativeWork",
    name: collapseWhitespace(image.title || "AI 生成作品"),
    url: new URL(`/gallery/${encodeURIComponent(image.slug)}`, origin).toString(),
    image: {
      "@type": "ImageObject",
      url: image.asset.url,
      contentUrl: image.asset.url,
      width: image.asset.width,
      height: image.asset.height,
      encodingFormat: image.asset.mimeType,
    },
    datePublished: image.publishedAt,
    inLanguage: "zh-CN",
  };
  if (image.description) entry.description = image.description;
  if (image.creator?.displayName) {
    entry.creator = { "@type": "Person", name: image.creator.displayName };
  }
  return entry;
}

export interface ArtworkSeo {
  readonly title: string;
  readonly description: string;
  readonly canonicalUrl: string;
  readonly imageUrl: string;
}

/** 作品详情页的 <head> SEO 元数据。origin 可选，默认取公开来源。 */
export function buildArtworkSeo(image: GalleryImageDetail, origin?: URL): ArtworkSeo {
  const base = origin ?? resolvePublicOrigin();
  const title = collapseWhitespace(image.title || "AI 生成作品");
  const description = image.description
    || (image.workflowName ? `使用 ${image.workflowName} 工作流生成的 AI 作品。` : "Mavis Gallery 上的 AI 生成作品。");
  return {
    title,
    description,
    canonicalUrl: new URL(`/gallery/${encodeURIComponent(image.slug)}`, base).toString(),
    imageUrl: image.asset.url,
  };
}

/** 将 JSON-LD 对象序列化为可安全嵌入 <script type="application/ld+json"> 的字符串。 */
export function serializeJsonLd(value: unknown): string {
  const json = JSON.stringify(value) ?? "{}";
  // 转义所有 < >，防止内容中的 </script> 提前闭合标签。
  return json.replace(/</g, "\\u003c").replace(/>/g, "\\u003e");
}

function collapseWhitespace(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function isLoopback(hostname: string): boolean {
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1" || hostname === "[::1]";
}
