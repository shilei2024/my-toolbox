import type { Metadata } from "next";
import Link from "next/link";
import type { TaskSummary } from "@/lib/task-types";
import { GalleryClientError, getTasks } from "@/server/gallery-client";
import { resolveViewerFromRequest } from "@/server/viewer";

export const metadata: Metadata = { title: "任务中心", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";

export default async function TasksPage() {
  const viewer = await resolveViewerFromRequest();
  if (viewer.role === "guest") return <main className="page-shell"><TaskHeader /><section className="task-empty"><h2>登录后查看任务</h2><p>任务状态、积分结算和生成结果只对任务所有者可见。</p><Link className="button primary" href="/login?next=/tasks">登录</Link></section></main>;
  let items: readonly TaskSummary[] = [];
  let message: string | undefined;
  try { items = (await getTasks(viewer)).items; } catch (error) { message = error instanceof GalleryClientError ? error.message : "暂时无法读取任务中心，请稍后重试。"; }
  return <main className="page-shell"><TaskHeader />
    {message ? <p className="inline-error" role="alert">{message}</p> : null}
    {items.length === 0 && !message ? <section className="task-empty"><h2>还没有任务</h2><p>从创作台开始后，任务进度、成本和结果会集中显示在这里。</p><Link className="button primary" href="/create">开始创作</Link></section> : null}
    {items.length > 0 ? <section className="task-center-list" aria-label="任务列表">{items.map((task) => <TaskRow key={task.key} task={task} />)}</section> : null}
  </main>;
}

function TaskHeader() { return <section className="collection-head"><p className="eyebrow"><span className="eyebrow-dot" />Task center</p><h1 className="collection-title">任务中心</h1><p className="collection-copy">集中查看跨模块异步任务的状态、积分结算与输出。当前已接入图像生成，后续模块会沿用同一任务契约。</p></section>; }
function TaskRow({ task }: { readonly task: TaskSummary }) {
  const output = task.outputLinks[0];
  return <article className="task-center-item"><span className={`task-indicator ${task.status}`} aria-hidden="true" /><div className="task-center-main"><div><span className="task-module">{task.module === "generation" ? "图像生成" : task.module}</span><strong>{task.title}</strong></div><small>任务 {task.sourceId.slice(0, 8)} · 创建于 {formatTime(task.createdAt)} · {statusLabel(task.status, task.cancelRequested)}</small>{task.error ? <small className="task-error">{task.error.message}</small> : null}</div><div className="task-center-cost"><span>{task.status === "completed" ? "已结算" : "预占"}</span><strong>{task.status === "completed" ? task.creditsCharged : task.creditsReserved} 积分</strong></div>{output ? <Link className="button task-output" href={`/gallery/${output.slug}`}>查看结果</Link> : <Link className="button task-output" href="/create">创作台</Link>}</article>;
}
function statusLabel(status: TaskSummary["status"], cancelling: boolean) { if (cancelling && (status === "pending" || status === "running")) return "取消中"; return ({ pending: "排队中", running: "执行中", completed: "已完成", failed: "失败", cancelled: "已取消" })[status]; }
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
