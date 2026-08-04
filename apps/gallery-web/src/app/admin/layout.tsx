import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { resolveViewerFromRequest } from "@/server/viewer";

export const metadata: Metadata = { title: "管理后台", robots: { index: false, follow: false } };

export default async function AdminLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const viewer = await resolveViewerFromRequest();
  if (viewer.role !== "admin") notFound();
  return children;
}
