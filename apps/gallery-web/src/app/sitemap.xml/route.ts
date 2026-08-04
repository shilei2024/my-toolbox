import { resolvePublicOrigin } from "@/lib/seo";
import { getSitemapImages } from "@/server/seo-client";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const origin = resolvePublicOrigin();
  const entries: SitemapEntry[] = [{ url: new URL("/gallery", origin).toString(), changeFrequency: "hourly", priority: 1 }];
  try {
    const images = await getSitemapImages();
    entries.push(...images.map((image) => ({
      url: new URL(`/gallery/${encodeURIComponent(image.slug)}`, origin).toString(),
      lastModified: image.publishedAt,
      changeFrequency: "monthly" as const,
      priority: 0.8,
      imageUrl: image.assetUrl,
    })));
  } catch {
    // Keep a valid discovery entry while the internal Gallery service recovers.
  }
  return new Response(renderSitemap(entries), {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}

interface SitemapEntry {
  readonly url: string;
  readonly lastModified?: string;
  readonly changeFrequency: "hourly" | "monthly";
  readonly priority: number;
  readonly imageUrl?: string;
}

function renderSitemap(entries: readonly SitemapEntry[]): string {
  const urls = entries.map((entry) => `<url><loc>${xml(entry.url)}</loc>${entry.imageUrl ? `<image:image><image:loc>${xml(entry.imageUrl)}</image:loc></image:image>` : ""}${entry.lastModified ? `<lastmod>${xml(entry.lastModified)}</lastmod>` : ""}<changefreq>${entry.changeFrequency}</changefreq><priority>${entry.priority.toFixed(1)}</priority></url>`).join("");
  return `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">${urls}</urlset>`;
}

function xml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}
