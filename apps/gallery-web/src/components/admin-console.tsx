"use client";

/* eslint-disable @next/next/no-img-element */
import { useState, type FormEvent } from "react";
import type { AdminDashboard, AdminImageItem, AdminProviderItem, AdminProviderModelItem, AdminWorkflowItem } from "@/lib/admin-types";

type AdminTab = "moderation" | "providers" | "workflows" | "jobs" | "audit";

export function AdminConsole({ initialDashboard }: { readonly initialDashboard: AdminDashboard }) {
  const [dashboard, setDashboard] = useState(initialDashboard);
  const [tab, setTab] = useState<AdminTab>("moderation");
  const [busy, setBusy] = useState<string>();
  const [message, setMessage] = useState<string>();

  async function refresh() {
    const response = await fetch("/api/admin/dashboard", { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw await apiError(response);
    setDashboard(await response.json() as AdminDashboard);
  }

  async function run(key: string, action: () => Promise<void>, success: string) {
    setBusy(key); setMessage(undefined);
    try { await action(); await refresh(); setMessage(success); }
    catch (error) { setMessage(error instanceof Error ? error.message : "操作未完成，请刷新后重试。"); }
    finally { setBusy(undefined); }
  }

  async function moderate(image: AdminImageItem, decision: "approved" | "rejected") {
    if (decision === "rejected" && !window.confirm("确认拒绝这件作品？它将不会出现在公开 Gallery 与 SEO 中。")) return;
    await run(`image:${image.id}`, async () => {
      await mutate(`/api/admin/images/${encodeURIComponent(image.id)}/moderation`, "PATCH", { decision, reasonCodes: [decision === "approved" ? "manual_approved" : "manual_rejected"], expectedUpdatedAt: image.updatedAt });
    }, decision === "approved" ? "作品已批准并进入公开发布流程。" : "作品已拒绝并从公开发现路径移除。");
  }

  async function remove(image: AdminImageItem) {
    if (!window.confirm("确认删除这件作品？系统会先软删除，并按保留期清理 COS 对象。")) return;
    await run(`image:${image.id}`, async () => { await mutate(`/api/images/${encodeURIComponent(image.id)}`, "DELETE"); }, "作品已软删除。");
  }

  async function updateProvider(provider: AdminProviderItem, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await run(`provider:${provider.id}`, async () => {
      await mutate(`/api/admin/providers/${encodeURIComponent(provider.id)}`, "PATCH", { status: data.get("status"), priority: Number(data.get("priority")), expectedUpdatedAt: provider.updatedAt });
    }, `${provider.displayName} 已更新。`);
  }

  async function updateWorkflow(workflow: AdminWorkflowItem, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await run(`workflow:${workflow.id}`, async () => {
      await mutate(`/api/admin/workflows/${encodeURIComponent(workflow.id)}`, "PATCH", { isEnabled: data.get("isEnabled") === "on", sortOrder: Number(data.get("sortOrder")), expectedUpdatedAt: workflow.updatedAt });
    }, `${workflow.name} 已更新。`);
  }

  async function updateProviderModel(model: AdminProviderModelItem, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const creditRaw = String(data.get("creditCost") ?? "").trim();
    const creditCost = creditRaw === "" ? undefined : Number(creditRaw);
    if (creditCost !== undefined && (!Number.isFinite(creditCost) || creditCost < 0)) {
      setMessage("单张积分必须是大于等于 0 的数字，或留空。");
      return;
    }
    await run(`model:${model.id}`, async () => {
      await mutate(`/api/admin/provider-models/${encodeURIComponent(model.id)}`, "PATCH", {
        tier: data.get("tier"),
        ...(creditCost === undefined ? {} : { creditCost }),
        isDefault: data.get("isDefault") === "on",
        isEnabled: data.get("isEnabled") === "on",
        expectedUpdatedAt: model.updatedAt,
      });
    }, `${model.displayName} 已更新。`);
  }

  const stats = [
    ["待审核", dashboard.overview.pendingModeration, "需要人工决定"],
    ["公开作品", dashboard.overview.publicImages, "当前可被发现"],
    ["24h 任务", dashboard.overview.jobsLast24Hours, "最近生成请求"],
    ["24h 失败", dashboard.overview.failedJobsLast24Hours, "需要观察"],
    ["活跃 Provider", dashboard.overview.activeProviders, "参与路由"],
    ["启用工作流", dashboard.overview.enabledWorkflows, "可供选择"],
  ] as const;

  return <>
    <section className="admin-stats" aria-label="运行概览">{stats.map(([label, value, note], index) => <article className={`admin-stat ${index === 0 && value > 0 ? "attention" : ""}`} key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>)}</section>
    <section className="admin-workspace">
      <nav className="admin-tabs" aria-label="后台功能">{([[
        "moderation", `内容审核 ${dashboard.overview.pendingModeration}`], ["providers", "Provider"], ["workflows", "工作流"], ["jobs", "生成任务"], ["audit", "审计记录"]] as const).map(([value, label]) => <button key={value} type="button" className={tab === value ? "active" : ""} onClick={() => setTab(value)} aria-pressed={tab === value}>{label}</button>)}</nav>
      {message && <p className="admin-message" role="status">{message}</p>}
      <div className="admin-section">
        {tab === "moderation" && <ModerationPanel items={dashboard.moderationQueue} busy={busy} onModerate={moderate} onDelete={remove} />}
        {tab === "providers" && <><ProviderPanel items={dashboard.providers} busy={busy} onSubmit={updateProvider} /><ProviderModelsPanel items={dashboard.providers} busy={busy} onSubmit={updateProviderModel} /></>}
        {tab === "workflows" && <WorkflowPanel items={dashboard.workflows} busy={busy} onSubmit={updateWorkflow} />}
        {tab === "jobs" && <JobsPanel dashboard={dashboard} />}
        {tab === "audit" && <AuditPanel dashboard={dashboard} />}
      </div>
    </section>
  </>;
}

function ModerationPanel({ items, busy, onModerate, onDelete }: { readonly items: readonly AdminImageItem[]; readonly busy?: string; readonly onModerate: (item: AdminImageItem, decision: "approved" | "rejected") => void; readonly onDelete: (item: AdminImageItem) => void }) {
  if (!items.length) return <AdminEmpty title="审核队列已清空" copy="新的 pending 或 manual review 作品会出现在这里。" />;
  return <div className="moderation-list">{items.map((item) => <article className="moderation-card" key={item.id}><a className="moderation-thumb" href={`/gallery/${item.slug}`} target="_blank" rel="noreferrer"><img src={item.thumbnailUrl} alt={item.title || "待审核 AI 作品"} /></a><div className="moderation-copy"><div className="admin-row-title"><div><p>{item.title || "未命名作品"}</p><span>{item.workflowName} · {formatDate(item.createdAt)}</span></div><Status value={item.moderationStatus} /></div><dl className="admin-inline-meta"><div><dt>图片</dt><dd>{item.visibility}</dd></div><div><dt>Prompt</dt><dd>{item.promptVisibility}</dd></div><div><dt>Slug</dt><dd>{item.slug}</dd></div></dl><div className="admin-row-actions"><button className="button primary" type="button" disabled={busy === `image:${item.id}`} onClick={() => onModerate(item, "approved")}>批准公开</button><button className="button" type="button" disabled={busy === `image:${item.id}`} onClick={() => onModerate(item, "rejected")}>拒绝</button><button className="button danger" type="button" disabled={busy === `image:${item.id}`} onClick={() => onDelete(item)}>删除</button></div></div></article>)}</div>;
}

function ProviderPanel({ items, busy, onSubmit }: { readonly items: readonly AdminProviderItem[]; readonly busy?: string; readonly onSubmit: (item: AdminProviderItem, event: FormEvent<HTMLFormElement>) => void }) {
  if (!items.length) return <AdminEmpty title="还没有 Provider" copy="Provider 注册属于服务端部署流程，后台只管理已注册实例。" />;
  return <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Provider</th><th>状态</th><th>优先级</th><th>凭证</th><th>健康</th><th>操作</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.displayName}</strong><small>{item.code} / {item.adapterType}</small></td><td><Status value={item.status} /></td><td colSpan={4}><form className="admin-inline-form" onSubmit={(event) => onSubmit(item, event)}><select name="status" defaultValue={item.status === "active" ? "active" : "disabled"} aria-label={`${item.displayName} 状态`}><option value="active">active</option><option value="disabled">disabled</option></select><input name="priority" type="number" min="0" max="10000" defaultValue={item.priority} aria-label={`${item.displayName} 优先级`} /><span className="credential-mark">{item.secretConfigured ? "已配置" : "未配置"}</span><span className="health-copy">失败 {item.consecutiveFailures} 次<br />{item.lastHealthAt ? formatDate(item.lastHealthAt) : "尚未检查"}</span><button className="button" type="submit" disabled={busy === `provider:${item.id}`}>保存</button></form></td></tr>)}</tbody></table></div>;
}

function ProviderModelsPanel({ items, busy, onSubmit }: { readonly items: readonly AdminProviderItem[]; readonly busy?: string; readonly onSubmit: (model: AdminProviderModelItem, event: FormEvent<HTMLFormElement>) => void }) {
  if (!items.some((item) => item.models.length)) return null;
  return <div className="admin-models">
    <div className="admin-models-title">模型与计分（tier=free 免费积分可用；tier=member 需会员积分）</div>
    {items.map((item) => item.models.map((model) => (
      <form key={model.id} className="admin-model-row" onSubmit={(event) => onSubmit(model, event)}>
        <span className="admin-model-provider">{item.displayName}</span>
        <code>{model.modelCode}</code>
        <span className="admin-model-name">{model.displayName}</span>
        <select name="tier" defaultValue={model.tier} aria-label="积分档位">
          <option value="free">free</option>
          <option value="member">member</option>
        </select>
        <input name="creditCost" type="number" min="0" step="0.0001" defaultValue={model.creditCost ?? ""} placeholder="单张积分" aria-label="单张积分" />
        <label><input name="isDefault" type="checkbox" defaultChecked={model.isDefault} />默认</label>
        <label><input name="isEnabled" type="checkbox" defaultChecked={model.isEnabled} />启用</label>
        <button className="button" type="submit" disabled={busy === `model:${model.id}`}>保存</button>
      </form>
    )))}
  </div>;
}

function WorkflowPanel({ items, busy, onSubmit }: { readonly items: readonly AdminWorkflowItem[]; readonly busy?: string; readonly onSubmit: (item: AdminWorkflowItem, event: FormEvent<HTMLFormElement>) => void }) {
  if (!items.length) return <AdminEmpty title="还没有工作流" copy="先通过版本化发布流程创建工作流，再在这里控制启用和排序。" />;
  return <div className="workflow-admin-grid">{items.map((item) => <form className="workflow-admin-card" key={item.id} onSubmit={(event) => onSubmit(item, event)}><div className="admin-row-title"><div><p>{item.name}</p><span>{item.slug} · {item.category}</span></div><Status value={item.isEnabled ? "enabled" : "disabled"} /></div><div className="workflow-version"><span>Active version</span><strong>{item.activeVersion ? `v${item.activeVersion}` : "未发布"}</strong><small>{item.bindingCount} 个可用 binding</small></div><div className="workflow-controls"><label><input name="isEnabled" type="checkbox" defaultChecked={item.isEnabled} />允许用户选择</label><label>排序<input name="sortOrder" type="number" min="0" max="10000" defaultValue={item.sortOrder} /></label><button className="button" type="submit" disabled={busy === `workflow:${item.id}`}>保存工作流</button></div></form>)}</div>;
}

function JobsPanel({ dashboard }: { readonly dashboard: AdminDashboard }) {
  if (!dashboard.recentJobs.length) return <AdminEmpty title="暂无生成任务" copy="最近的任务状态会在这里显示，不包含 Prompt 内容。" />;
  return <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>任务</th><th>工作流</th><th>Provider</th><th>状态</th><th>实际成本</th><th>创建时间</th></tr></thead><tbody>{dashboard.recentJobs.map((item) => <tr key={item.id}><td><code>{shortId(item.id)}</code></td><td>{item.workflowName}</td><td>{item.providerCode || "尚未选择"}</td><td><Status value={item.status} /></td><td>{item.actualCost.toFixed(4)}</td><td>{formatDate(item.createdAt)}</td></tr>)}</tbody></table></div>;
}

function AuditPanel({ dashboard }: { readonly dashboard: AdminDashboard }) {
  if (!dashboard.recentAudit.length) return <AdminEmpty title="暂无管理审计" copy="审核、Provider 和工作流变更会记录在这里。" />;
  return <ol className="audit-list">{dashboard.recentAudit.map((item) => <li key={item.id}><span className="audit-line" /><div><strong>{item.action}</strong><p>{item.resourceType} / {item.resourceId ? shortId(item.resourceId) : "—"}</p></div><time>{formatDate(item.createdAt)}</time></li>)}</ol>;
}

function Status({ value }: { readonly value: string }) { return <span className={`status-pill status-${value.replace("_", "-")}`}>{value}</span>; }
function AdminEmpty({ title, copy }: { readonly title: string; readonly copy: string }) { return <div className="admin-empty"><span>0</span><h2>{title}</h2><p>{copy}</p></div>; }
function shortId(value: string): string { return value.length > 12 ? `${value.slice(0, 8)}…` : value; }
function formatDate(value: string): string { return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai" }).format(new Date(value)); }

async function mutate(path: string, method: "PATCH" | "DELETE", body?: unknown): Promise<void> {
  const response = await fetch(path, { method, credentials: "same-origin", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (!response.ok) throw await apiError(response);
}

async function apiError(response: Response): Promise<Error> {
  try { const body = await response.json() as { error?: { message?: string } }; return new Error(body.error?.message || "操作未完成，请刷新后重试。"); }
  catch { return new Error("操作未完成，请刷新后重试。"); }
}
