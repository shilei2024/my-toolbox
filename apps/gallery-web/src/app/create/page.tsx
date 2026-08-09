import type { Metadata } from "next";
import { GenerationWorkbench } from "@/components/generation-workbench";

export const metadata: Metadata = {
  title: "开始创作",
  description: "使用 Mavis AI 工具平台创作图片。",
  robots: { index: false, follow: false },
};

// Must render dynamically: the CSP middleware injects a per-request nonce
// during SSR, and Next.js only applies it to scripts on dynamically rendered
// pages. Static prerendering would ship the HTML without the nonce while the
// response still carries a strict-dynamic CSP, blocking every script on a
// full page load (e.g. entering /create from the main site).
export const dynamic = "force-dynamic";

export default function CreatePage() {
  return <GenerationWorkbench />;
}
