import type { Metadata } from "next";
import { GenerationWorkbench } from "@/components/generation-workbench";

export const metadata: Metadata = {
  title: "开始创作",
  description: "使用 Mavis AI 工具平台创作图片。",
  robots: { index: false, follow: false },
};

export default function CreatePage() {
  return <GenerationWorkbench />;
}
