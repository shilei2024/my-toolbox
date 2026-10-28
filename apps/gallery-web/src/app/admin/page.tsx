import { redirect } from "next/navigation";
import { AdminConsole } from "@/components/admin-console";
import type { AdminDashboard } from "@/lib/admin-types";
import { adminConsoleUrl } from "@/lib/admin-links";
import { GalleryClientError } from "@/server/gallery-client";
import { getAdminDashboard } from "@/server/admin-client";
import { resolveViewerFromRequest } from "@/server/viewer";

export default async function AdminPage() {
  const viewer = await resolveViewerFromRequest();
  const unifiedAdmin = adminConsoleUrl();
  if (unifiedAdmin) redirect(unifiedAdmin);
  let dashboard: AdminDashboard | undefined;
  let error: string | undefined;
  try { dashboard = await getAdminDashboard(viewer); }
  catch (reason) { error = reason instanceof GalleryClientError ? reason.message : "管理服务暂时不可用"; }
  return <main className="admin-shell"><header className="admin-masthead"><div><p className="eyebrow"><span className="eyebrow-dot" />Control / Phase 08</p><h1>运营控制台</h1><p>审核内容、控制可用能力，并让每一次变更都留下可追溯记录。</p></div><div className="admin-identity"><span>管理员</span><strong>#{viewer.userId}</strong></div></header>{dashboard ? <AdminConsole initialDashboard={dashboard} /> : <section className="state-stage error-state"><div className="state-message"><div className="state-mark">!</div><h2>暂时无法读取后台数据</h2><p>{error}</p></div></section>}</main>;
}
