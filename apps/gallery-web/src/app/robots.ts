import type { MetadataRoute } from "next";
import { resolvePublicOrigin } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  const origin = resolvePublicOrigin();
  return {
    rules: {
      userAgent: "*",
      allow: ["/", "/gallery", "/gallery/"],
      disallow: ["/api/", "/my-images", "/favorites", "/admin/", "/generation-history"],
    },
    sitemap: new URL("/sitemap.xml", origin).toString(),
    host: origin.origin,
  };
}
