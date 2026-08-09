"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { BillingSummary } from "@/lib/billing-types";
import type { GenerationMode, GenerationPage, GenerationView, GenerationVisibility, GenerationWorkflow } from "@/lib/generation-types";

type LoadState = "loading" | "ready" | "error";
const terminal = new Set(["completed", "failed", "cancelled"]);
const RECENT_LIMIT = 8;
interface SessionView { readonly role: "guest" | "user" | "admin" }

export function GenerationWorkbench() {
  const [workflows, setWorkflows] = useState<readonly GenerationWorkflow[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [recent, setRecent] = useState<readonly GenerationView[]>([]);
  const [recentState, setRecentState] = useState<LoadState>("loading");
  const [previewUrls, setPreviewUrls] = useState<Readonly<Record<string, string>>>({});
  const [selected, setSelected] = useState("");
  const [mode, setMode] = useState<GenerationMode>("workflow");
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [size, setSize] = useState("1024x1024");
  const [count, setCount] = useState(1);
  const [visibility, setVisibility] = useState<GenerationVisibility>("public");
  const [promptVisibility, setPromptVisibility] = useState<"public" | "hidden">("public");
  const [creditTier, setCreditTier] = useState<"free" | "member">("free");
  const [generation, setGeneration] = useState<GenerationView>();
  const [billing, setBilling] = useState<BillingSummary>();
  const [session, setSession] = useState<SessionView>();
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<{ readonly timer?: ReturnType<typeof setTimeout> } | undefined>(undefined);
  const creationAttemptRef = useRef<{ readonly payload: string; readonly key: string } | undefined>(undefined);
  const mountedRef = useRef(false);

  const refreshRecent = useCallback(async () => {
    try {
      const body = await fetch(`/api/generations?limit=${RECENT_LIMIT}`, { cache: "no-store" }).then(readJson) as GenerationPage;
      if (Array.isArray(body.items)) {
        if (mountedRef.current) {
          setRecent(body.items);
          setRecentState("ready");
        }
      }
    } catch {
      if (mountedRef.current) setRecentState("error");
    }
  }, []);

  const loadPreviews = useCallback(async (slugs: readonly string[]) => {
    const entries = await Promise.all(slugs.map(async (slug) => {
      try {
        const detail = await fetch(`/api/gallery/${encodeURIComponent(slug)}`, { cache: "no-store" }).then(readJson) as { asset?: { url?: unknown } };
        return typeof detail.asset?.url === "string" ? [slug, detail.asset.url] as const : undefined;
      } catch { return undefined; }
    }));
    setPreviewUrls((current) => {
      const next = { ...current };
      for (const entry of entries) if (entry) next[entry[0]] = entry[1];
      return next;
    });
  }, []);

  const fetchComposerData = useCallback(async () => {
    const [workflowBody, sessionBody] = await Promise.all([
      fetch("/api/generation/workflows", { cache: "no-store" }).then(readJson),
      fetch("/api/me/session", { cache: "no-store" }).then(readJson).catch(() => undefined),
    ]);
    const items = (workflowBody as { items?: unknown }).items;
    if (!Array.isArray(items) || items.length === 0) throw new Error("暂时没有可用的创作方式。");
    const workflows = items as GenerationWorkflow[];
    const billingBody = await fetch("/api/billing/summary", { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() as Promise<BillingSummary> : undefined)
      .catch(() => undefined);
    return { workflows, session: parseSession(sessionBody), billing: billingBody };
  }, []);

  const selectWorkflow = useCallback((item: GenerationWorkflow) => {
    setSelected(item.slug);
    setSize(initialSize(item));
    setCount(initialCount(item));
    setVisibility(item.defaults.visibility ?? "public");
    setPromptVisibility(item.defaults.promptVisibility ?? "public");
  }, []);

  const applyComposerData = useCallback((data: Awaited<ReturnType<typeof fetchComposerData>>) => {
    setWorkflows(data.workflows);
    setMode(data.workflows[0]!.mode ?? "workflow");
    selectWorkflow(data.workflows[0]!);
    setSession(data.session);
    setBilling(data.billing);
  }, [selectWorkflow]);

  const switchMode = useCallback((next: GenerationMode) => {
    setMode(next);
    const first = workflows.find((item) => (item.mode ?? "workflow") === next);
    if (first) selectWorkflow(first);
  }, [selectWorkflow, workflows]);

  useEffect(() => {
    let active = true;
    mountedRef.current = true;
    fetchComposerData().then((data) => {
      if (!active) return;
      applyComposerData(data);
      setLoadState("ready");
    }).catch((error) => { if (active) { setLoadState("error"); setMessage(error instanceof Error ? error.message : "创作服务暂时不可用。"); } });
    fetch(`/api/generations?limit=${RECENT_LIMIT}`, { cache: "no-store" })
      .then(readJson)
      .then((body) => {
        const items = (body as { items?: unknown }).items;
        if (active && Array.isArray(items)) {
          setRecent(items as GenerationView[]);
          setRecentState("ready");
        }
      })
      .catch(() => { if (active) setRecentState("error"); });
    return () => { active = false; mountedRef.current = false; if (pollRef.current?.timer) clearTimeout(pollRef.current.timer); };
  }, [applyComposerData, fetchComposerData]);

  function retryLoad() {
    setLoadState("loading");
    setMessage("");
    void fetchComposerData()
      .then((data) => { applyComposerData(data); setLoadState("ready"); })
      .catch((error) => { setLoadState("error"); setMessage(error instanceof Error ? error.message : "创作服务暂时不可用。"); });
    void refreshRecent();
  }

  const workflow = useMemo(() => workflows.find((item) => item.slug === selected), [workflows, selected]);
  const visibleWorkflows = useMemo(() => workflows.filter((item) => (item.mode ?? "workflow") === mode), [mode, workflows]);
  const estimate = workflow ? (Number(workflow.creditCost) * count).toFixed(4).replace(/\.0+$/, "") : "—";
  const loggedIn = (session !== undefined && session.role !== "guest") || billing?.account !== undefined;

  async function submit() {
    if (!workflow || submitting || prompt.trim().length === 0) return;
    setSubmitting(true); setMessage("");
    const [width, height] = size.split("x").map(Number) as [number, number];
    try {
      const payload = JSON.stringify({ workflowSlug: workflow.slug, prompt: prompt.trim(), negativePrompt: negativePrompt.trim(), width, height, count, visibility, promptVisibility, creditTier, parameters: {} });
      if (creationAttemptRef.current?.payload !== payload) creationAttemptRef.current = { payload, key: crypto.randomUUID() };
      const response = await fetch("/api/generations", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": creationAttemptRef.current.key },
        body: payload,
      });
      const created = await readJson(response) as GenerationView;
      creationAttemptRef.current = undefined;
      setGeneration(created);
      void refreshRecent();
      schedulePoll(created.id);
    } catch (error) { setMessage(error instanceof Error ? error.message : "任务创建失败，请稍后重试。"); }
    finally { setSubmitting(false); }
  }

  function schedulePoll(id: string, nextDelayMs = 2000) {
    if (!mountedRef.current) return;
    if (pollRef.current?.timer) clearTimeout(pollRef.current.timer);
    const timer = setTimeout(async () => {
      if (!mountedRef.current) return;
      try {
        const current = await fetch(`/api/generations/${encodeURIComponent(id)}`, { cache: "no-store" }).then(readJson) as GenerationView;
        if (!mountedRef.current) return;
        setGeneration(current);
        if (current.status === "completed" && current.images.length > 0) {
          void loadPreviews(current.images.map((image) => image.slug));
        }
        if (!terminal.has(current.status)) schedulePoll(id, 2000);
        else void refreshRecent();
      } catch (error) {
        if (!mountedRef.current) return;
        // Transient failures must not silently stop progress updates; back off
        // and keep polling so the task can still reach its terminal state.
        setMessage(error instanceof Error ? error.message : "任务状态更新失败。");
        schedulePoll(id, Math.min(nextDelayMs * 2, 10_000));
      }
    }, nextDelayMs);
    pollRef.current = { timer };
  }

  async function cancel() {
    if (!generation || terminal.has(generation.status)) return;
    setMessage("");
    try {
      const result = await fetch(`/api/generations/${encodeURIComponent(generation.id)}`, { method: "DELETE" }).then(readJson) as { generation: GenerationView; accepted: boolean };
      setGeneration(result.generation);
      void refreshRecent();
      if (!terminal.has(result.generation.status)) schedulePoll(result.generation.id);
    } catch (error) { setMessage(error instanceof Error ? error.message : "取消请求失败。"); }
  }

  function selectTask(item: GenerationView) {
    setGeneration(item);
    if (!terminal.has(item.status)) schedulePoll(item.id);
    if (item.status === "completed") void loadPreviews(item.images.map((image) => image.slug));
  }

  async function cancelTask(item: GenerationView) {
    if (terminal.has(item.status)) return;
    setMessage("");
    try {
      const result = await fetch(`/api/generations/${encodeURIComponent(item.id)}`, { method: "DELETE" }).then(readJson) as { generation: GenerationView; accepted: boolean };
      setRecent((current) => current.map((entry) => entry.id === item.id ? result.generation : entry));
      if (generation?.id === item.id) setGeneration(result.generation);
      if (!terminal.has(result.generation.status)) schedulePoll(result.generation.id);
      void refreshRecent();
    } catch (error) { setMessage(error instanceof Error ? error.message : "取消请求失败。"); }
  }

  function retryTask(item: GenerationView) {
    const target = workflows.find((entry) => entry.slug === item.workflowSlug);
    if (!target) {
      setMessage("该创作方式当前不可用，无法回填重试。");
      return;
    }
    setMode(target.mode ?? "workflow");
    setSelected(target.slug);
    setSize(`${item.width}x${item.height}`);
    setCount(item.count);
    setVisibility(item.visibility);
    setPromptVisibility(item.promptVisibility);
    setPrompt(item.prompt);
    setNegativePrompt(item.negativePrompt);
    setMessage("已回填上次参数，可修改后点击“开始生成”重新创作。");
  }

  return <main className="create-shell">
    <section className="create-heading" aria-labelledby="create-title">
      <div><p className="eyebrow"><span className="eyebrow-dot" />AI IMAGE STUDIO</p><h1 id="create-title">把一个想法，变成一张<span>值得留下的图。</span></h1><p>选择创作方式并描述画面。实际模型、供应商选择和故障降级由平台统一处理。</p></div>
      <div className="create-account-note" aria-label="账户状态"><span>当前账户</span><strong>{loggedIn ? (billing?.account ? `${billing.account.availableAmount} 可用积分` : "已登录") : "登录后可开始创作"}</strong><small>{loggedIn ? (billing?.account ? `${billing.account.reservedAmount} 积分正在任务中` : "积分余额暂时无法显示") : "与工具网站共用同一用户账户"}</small></div>
    </section>

    <div className="workbench-grid">
      <form className="composer-panel" aria-label="AI 生图创作参数" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <div className="panel-heading"><div><span className="step-index">01</span><h2>选择创作方式</h2></div><span className="panel-hint">工作流与 API 模型分开选择</span></div>
        {loadState === "loading" ? <div className="workflow-loading">正在读取平台工作流…</div> : loadState === "error" ? <div className="inline-error-row"><div className="inline-error">{message}</div><button className="button" type="button" onClick={retryLoad}>重试</button></div> : <>
          <div className="creation-mode-tabs" role="tablist" aria-label="创作方式分类">
            {(["workflow", "api"] as const).map((value) => <button key={value} type="button" role="tab" aria-selected={mode === value} className={`mode-tab${mode === value ? " active" : ""}`} onClick={() => switchMode(value)}>{value === "workflow" ? "工作流" : "API 模型"}<span className="mode-count">{workflows.filter((item) => item.mode === value).length}</span></button>)}
          </div>
          {visibleWorkflows.length === 0
            ? <div className="workflow-loading">该分类暂无可用方式，请切换分类或稍后再试。</div>
            : <div className="workflow-grid" role="radiogroup" aria-label={mode === "workflow" ? "工作流创作方式" : "API 模型创作方式"}>
              {visibleWorkflows.map((item) => <label className="workflow-option" key={item.slug}><input type="radio" name="workflow" value={item.slug} checked={selected === item.slug} onChange={() => selectWorkflow(item)} /><span className="workflow-tone">{item.category}</span><strong>{item.name}</strong><small>{item.description}</small></label>)}
            </div>}
        </>}

        <div className="composer-section"><div className="panel-heading compact"><div><span className="step-index">02</span><h2>描述你的画面</h2></div><span className="panel-hint">建议写清主体、环境、光线和质感</span></div>
          <label className="prompt-field"><span className="sr-only">画面描述</span><textarea required maxLength={2000} rows={7} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：夏日清晨的江南庭院，白墙黛瓦，薄雾穿过竹林，柔和自然光，安静而克制的电影质感……" /><small>{prompt.length} / 2000</small></label>
          <details className="advanced-prompt"><summary>添加不希望出现的内容</summary><label><span className="sr-only">负面描述</span><textarea maxLength={2000} rows={3} value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} placeholder="例如：模糊、文字、水印、过度锐化" /></label></details>
        </div>

        <div className="composer-section parameter-section"><div className="panel-heading compact"><div><span className="step-index">03</span><h2>画面设置</h2></div></div><div className="parameter-grid">
          <label><span>积分档位</span><select value={creditTier} onChange={(event) => setCreditTier(event.target.value as "free" | "member")}><option value="free">免费积分</option><option value="member">会员积分</option></select></label>
          <label><span>画面比例</span><select value={size} onChange={(event) => setSize(event.target.value)}>{workflow?.sizes?.length ? workflow.sizes.map((item) => { const key = sizeKey(item); return <option key={key} value={key}>{sizeLabel(key)}</option>; }) : <option value={size}>加载中…</option>}</select></label>
          <label><span>生成数量</span><select value={count} onChange={(event) => setCount(Number(event.target.value))}>{workflow ? countOptions(workflow).map((value) => <option key={value} value={value}>{value} 张</option>) : <option value={count}>加载中…</option>}</select></label>
          <label><span>作品可见性</span><select value={visibility} onChange={(event) => setVisibility(event.target.value as GenerationVisibility)}><option value="private">仅自己可见</option><option value="public">公开到画廊</option></select></label>
        </div><label className="prompt-privacy"><input type="checkbox" checked={promptVisibility === "hidden"} onChange={(event) => setPromptVisibility(event.target.checked ? "hidden" : "public")} />隐藏作品 Prompt</label></div>

        {message && loadState !== "error" ? <div className="inline-error" role="alert">{message}</div> : null}
        <div className="composer-submit"><div><span>本次预计</span><strong>{estimate} 积分</strong></div>{loggedIn
          ? <button className="button primary create-submit" type="submit" disabled={loadState !== "ready" || submitting || prompt.trim().length === 0}>{submitting ? "正在创建…" : "开始生成"}</button>
          : <Link className="button primary create-submit" href="/login?next=/create">登录后生成</Link>}</div>
      </form>

      <aside className="creation-preview" aria-labelledby="preview-title">
        <div className={`preview-stage${generation ? ` task-${generation.status}` : ""}`}>
          {generation?.status === "completed" && generation.images.length > 0 ? (
            <div className="preview-images" style={{ aspectRatio: `${generation.width} / ${generation.height}` }}>
              {generation.images.map((image, index) => {
                const url = previewUrls[image.slug];
                return <Link className={`preview-image${url ? "" : " pending"}`} key={image.id} href={`/gallery/${image.slug}`} aria-label={`查看作品 ${index + 1}`}>{url ? <img src={url} alt={`作品 ${index + 1}`} loading="lazy" /> : <span>作品 {index + 1}</span>}</Link>;
              })}
            </div>
          ) : (<><div className="preview-orbit" aria-hidden="true"><span /><span /><span /></div><div className="preview-copy">{generation ? <span className="preview-kicker">{statusLabel(generation.status).toUpperCase()}</span> : null}<h2 id="preview-title">{generation ? statusLabel(generation.status) : "生成结果将显示在这里"}</h2><p>{generation ? taskDescription(generation) : ""}</p></div></>)}
          {generation?.images.length ? <div className="generated-links">{generation.images.map((image, index) => <Link key={image.id} href={`/gallery/${image.slug}`}>查看作品 {index + 1}</Link>)}</div> : null}
        </div>
        <div className="task-strip"><span className={`task-indicator${generation ? ` ${generation.status}` : ""}`} /><div><strong>{generation ? `${generation.workflowName} · ${statusLabel(generation.status)}` : "尚未创建任务"}</strong><small>{generation ? `任务 ${generation.id.slice(0, 8)} · ${generation.width}×${generation.height}` : "队列状态、耗时和取消操作将显示在这里"}</small></div>{generation && !terminal.has(generation.status) ? <button className="button task-cancel" type="button" onClick={() => void cancel()}>取消</button> : null}</div>
      </aside>
    </div>

    <section className="recent-panel" aria-labelledby="recent-title">
      <div className="panel-heading compact"><div><span className="step-index">04</span><h2 id="recent-title">最近创作</h2></div><span className="panel-hint">点击任务查看状态与结果，失败任务可回填重新创作</span></div>
      {recentState === "loading" ? <div className="workflow-loading">正在读取最近任务…</div>
        : recent.length === 0 ? <div className="recent-empty">最近任务会显示在这里。</div>
        : <div className="recent-list">{recent.map((item) => {
          const first = item.images[0];
          const firstUrl = first ? previewUrls[first.slug] : undefined;
          return <div className="recent-item" key={item.id}>
            <button className="recent-select" type="button" onClick={() => selectTask(item)}>
              <span className={`task-indicator ${item.status}`} />
              <span className="recent-thumb">{firstUrl ? <img src={firstUrl} alt="" loading="lazy" /> : <span>{item.status === "failed" ? "失败" : item.images.length ? `${item.images.length} 张` : "…"}</span>}</span>
              <span className="recent-main"><strong>{item.workflowName}</strong><small>{promptSummary(item.prompt)}</small></span>
              <span className="recent-meta"><em>{statusLabel(item.status)}</em><time>{formatTime(item.createdAt)}</time></span>
            </button>
            <div className="recent-actions">
              {!terminal.has(item.status) ? <button className="button recent-action" type="button" onClick={() => void cancelTask(item)}>取消</button> : null}
              {item.status === "failed" ? <button className="button primary recent-action" type="button" onClick={() => retryTask(item)}>重新创作</button> : null}
            </div>
          </div>;
        })}</div>}
    </section>
  </main>;
}

async function readJson(response: Response): Promise<unknown> {
  const body = response.headers.get("content-type")?.includes("application/json") ? await response.json() as unknown : undefined;
  if (response.ok) return body;
  const error = body && typeof body === "object" && !Array.isArray(body) ? (body as { error?: { message?: unknown } }).error : undefined;
  throw new Error(typeof error?.message === "string" ? error.message : "服务暂时不可用，请稍后重试。");
}
function statusLabel(status: GenerationView["status"]): string { return ({ pending: "排队中", running: "生成中", completed: "已完成", failed: "生成失败", cancelled: "已取消" })[status]; }
function taskDescription(generation: GenerationView): string {
  if (generation.status === "failed") return "可点击“重新创作”调整后重试。";
  if (generation.status === "running") return generation.cancelRequested ? "正在停止任务…" : "正在生成…";
  return "";
}
function promptSummary(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > 72 ? `${normalized.slice(0, 72)}…` : normalized || "未填写描述";
}
function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function parseSession(value: unknown): SessionView | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const role = (value as { role?: unknown }).role;
  return role === "guest" || role === "user" || role === "admin" ? { role } : undefined;
}
function initialSize(workflow: GenerationWorkflow): string {
  const fallback = { width: workflow.defaults.width, height: workflow.defaults.height };
  const sizes = workflow.sizes ?? [];
  const defaultKey = sizeKey(fallback);
  return sizes.some((item) => sizeKey(item) === defaultKey) ? defaultKey : sizeKey(sizes[0] ?? fallback);
}
function initialCount(workflow: GenerationWorkflow): number {
  const { min, max } = workflow.countRange;
  return Math.min(Math.max(workflow.defaults.count, min), max);
}
function sizeKey(size: { readonly width: number; readonly height: number }): string { return `${size.width}x${size.height}`; }
function sizeLabel(value: string): string {
  const [width, height] = value.split("x").map(Number) as [number, number];
  if (!Number.isFinite(width) || !Number.isFinite(height)) return value;
  const labels: ReadonlyArray<readonly [number, string]> = [
    [1, "1:1 方形"], [3 / 4, "3:4 竖图"], [4 / 3, "4:3 横图"], [9 / 16, "9:16 竖图"], [16 / 9, "16:9 横图"], [2 / 3, "2:3 竖图"], [3 / 2, "3:2 横图"],
  ];
  const label = labels.find(([ratio]) => Math.abs(ratio - width / height) < 0.01)?.[1] ?? `${width}×${height}`;
  return `${label}（${width}×${height}）`;
}
function countOptions(workflow: GenerationWorkflow): readonly number[] {
  const { min, max } = workflow.countRange ?? { min: 1, max: 4 };
  return [1, 2, 3, 4].filter((value) => value >= min && value <= max);
}
