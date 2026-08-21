import type { Metadata } from "next";
import { SiteHeader } from "@/components/site-header";
import { resolvePublicOrigin } from "@/lib/seo";
import { mainSiteUrl } from "@/lib/site-links";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: resolvePublicOrigin(),
  title: {
    default: "Mavis Gallery",
    template: "%s · Mavis Gallery",
  },
  description: "浏览 Mavis 社区公开且通过审核的 AI 图像作品。",
  applicationName: "Mavis Gallery",
  creator: "Mavis",
  publisher: "Mavis",
  formatDetection: { email: false, address: false, telephone: false },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1, "max-video-preview": -1 },
  },
  openGraph: {
    type: "website",
    locale: "zh_CN",
    siteName: "Mavis Gallery",
    title: "Mavis Gallery",
    description: "浏览 Mavis 社区公开且通过审核的 AI 图像作品。",
    url: "/gallery",
  },
  twitter: {
    card: "summary_large_image",
    title: "Mavis Gallery",
    description: "浏览 Mavis 社区公开且通过审核的 AI 图像作品。",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <SiteHeader mainSiteUrl={mainSiteUrl()} />
        {children}
      </body>
    </html>
  );
}
