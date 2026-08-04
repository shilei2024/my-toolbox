"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type { BillingSummary } from "@/lib/billing-types";
import type { GenerationView, GenerationVisibility, GenerationWorkflow } from "@/lib/generation-types";

type LoadState = "loading" | "ready" | "error";
const terminal = new Set(["completed", "failed", "cancelled"]);

export function GenerationWorkbench() {
  const [workflows, setWorkflows] = useState<readonly GenerationWorkflow[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [selected, setSelected] = useState("");
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [size, setSize] = useState("1024x1024");
  const [count, setCount] = useState(1);
  const [visibility, setVisibility] = useState<GenerationVisibility>("private");
  const [promptVisibility, setPromptVisibility] = useState<"public" | "hidden">("hidden");
  const [generation, setGeneration] = useState<GenerationView>();
  const [billing, setBilling] = useState<BillingSummary>();
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<{ readonly timer?: ReturnType<typeof setTimeout> } | undefined>(undefined);
  const creationAttemptRef = useRef<{ readonly payload: string; readonly key: string } | undefined>(undefined);

  useEffect(() => {
    let active = true;
    fetch("/api/generation/workflows", { cache: "no-store" }).then(readJson).then(async (workflowBody) => {
      const items = (workflowBody as { items?: unknown }).items;
      if (!Array.isArray(items) || items.length === 0) throw new Error("暂时没有可用的创作方式。");
      const next = items as GenerationWorkflow[];
      // Billing outages must not block the composer; the account note just stays empty.
      const billingBody = await fetch("/api/billing/summary", { cache: "no-store" })
        .then(async (response) => response.ok ? response.json() as Promise<BillingSummary> : undefined)
        .catch(() => undefined);
      if (!active) return;
      setWorkflows(next);
      setSelected(next[0]!.slug);
      setSize(`${next[0]!.defaults.width}x${next[0]!.defaults.height}`);
      setCount(next[0]!.defaults.count);
      setVisibility(next[0]!.defaults.visibility);
      setBilling(billingBody);
      setLoadState("ready");
    }).catch((error) => { if (active) { setLoadState("error"); setMessage(error instanceof Error ? error.message : "创作服务暂时不可用。"); } });
    return () => { active = false; if (pollRef.current?.timer) clearTimeout(pollRef.current.timer); };
  }, []);

  const workflow = useMemo(() => workflows.find((item) => item.slug === selected), [workflows, selected]);
  const estimate = workflow ? (Number(workflow.creditCost) * count).toFixed(4).replace(/\.0+$/, "") : "—";
  const loggedIn = billing?.account !== undefined;

  async function submit() {
    if (!workflow || submitting || prompt.trim().length === 0) return;
    setSubmitting(true); setMessage("");
    const [width, height] = size.split("x").map(Number) as [number, number];
    try {
      const payload = JSON.stringify({ workflowSlug: workflow.slug, prompt: prompt.trim(), negativePrompt: negativePrompt.trim(), width, height, count, visibility, promptVisibility, parameters: {} });
      if (creationAttemptRef.current?.payload !== payload) creationAttemptRef.current = { payload, key: crypto.randomUUID() };
      const response = await fetch("/api/generations", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": creationAttemptRef.current.key },
        body: payload,
      });
      const created = await readJson(response) as GenerationView;
      creationAttemptRef.current = undefined;
      setGeneration(created);
      schedulePoll(created.id);
    } catch (error) { setMessage(error instanceof Error ? error.message : "任务创建失败，请稍后重试。"); }
    finally { setSubmitting(false); }
  }

  function schedulePoll(id: string, nextDelayMs = 2000) {
    if (pollRef.current?.timer) clearTimeout(pollRef.current.timer);
    const timer = setTimeout(async () => {
      try {
        const current = await fetch(`/api/generations/${encodeURIComponent(id)}`, { cache: "no-store" }).then(readJson) as GenerationView;
        setGeneration(current);
        if (!terminal.has(current.status)) schedulePoll(id, 2000);
      } catch (error) {
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
      if (!terminal.has(result.generation.status)) schedulePoll(result.generation.id);
    } catch (error) { setMessage(error instanceof Error ? error.message : "取消请求失败。"); }
  }

  return <main className="create-shell">
    <section className="create-heading" aria-labelledby="create-title">
      <div><p className="eyebrow"><span className="eyebrow-dot" />AI IMAGE STUDIO</p><h1 id="create-title">把一个想法，变成一张<span>值得留下的图。</span></h1><p>选择创作方式并描述画面。实际模型、供应商选择和故障降级由平台统一处理。</p></div>
      <div className="create-account-note" aria-label="账户状态"><span>当前账户</span><strong>{loggedIn ? `${billing?.account?.availableAmount ?? "0"} 可用积分` : "登录后可开始创作"}</strong><small>{loggedIn ? `${billing?.account?.reservedAmount ?? "0"} 积分正在任务中` : "与工具网站共用同一用户账户"}</small></div>
    </section>

    <div className="workbench-grid">
      <form className="composer-panel" aria-label="AI 生图创作参数" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <div className="panel-heading"><div><span className="step-index">01</span><h2>选择创作方式</h2></div><span className="panel-hint">工作流决定画面的基础能力</span></div>
        {loadState === "loading" ? <div className="workflow-loading">正在读取平台工作流…</div> : loadState === "error" ? <div className="inline-error">{message}</div> : <div className="workflow-grid" role="radiogroup" aria-label="创作方式">
          {workflows.map((item) => <label className="workflow-option" key={item.slug}><input type="radio" name="workflow" value={item.slug} checked={selected === item.slug} onChange={() => { setSelected(item.slug); setSize(`${item.defaults.width}x${item.defaults.height}`); setCount(item.defaults.count); }} /><span className="workflow-tone">{item.category}</span><strong>{item.name}</strong><small>{item.description}</small></label>)}
        </div>}

        <div className="composer-section"><div className="panel-heading compact"><div><span className="step-index">02</span><h2>描述你的画面</h2></div><span className="panel-hint">建议写清主体、环境、光线和质感</span></div>
          <label className="prompt-field"><span className="sr-only">画面描述</span><textarea required maxLength={2000} rows={7} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：夏日清晨的江南庭院，白墙黛瓦，薄雾穿过竹林，柔和自然光，安静而克制的电影质感……" /><small>{prompt.length} / 2000</small></label>
          <details className="advanced-prompt"><summary>添加不希望出现的内容</summary><label><span className="sr-only">负面描述</span><textarea maxLength={2000} rows={3} value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} placeholder="例如：模糊、文字、水印、过度锐化" /></label></details>
        </div>

        <div className="composer-section parameter-section"><div className="panel-heading compact"><div><span className="step-index">03</span><h2>画面设置</h2></div></div><div className="parameter-grid">
          <label><span>画面比例</span><select value={size} onChange={(event) => setSize(event.target.value)}><option value="1024x1024">1:1 方形</option><option value="768x1024">3:4 竖图</option><option value="1024x768">4:3 横图</option></select></label>
          <label><span>生成数量</span><select value={count} onChange={(event) => setCount(Number(event.target.value))}><option value={1}>1 张</option><option value={2}>2 张</option><option value={4}>4 张</option></select></label>
          <label><span>作品可见性</span><select value={visibility} onChange={(event) => setVisibility(event.target.value as GenerationVisibility)}><option value="private">仅自己可见</option><option value="public">公开到画廊</option></select></label>
        </div><label className="prompt-privacy"><input type="checkbox" checked={promptVisibility === "hidden"} onChange={(event) => setPromptVisibility(event.target.checked ? "hidden" : "public")} />隐藏作品 Prompt</label></div>

        {message && loadState !== "error" ? <div className="inline-error" role="alert">{message}</div> : null}
        <div className="composer-submit"><div><span>本次预计</span><strong>{estimate} 积分</strong></div>{loggedIn
          ? <button className="button primary create-submit" type="submit" disabled={loadState !== "ready" || submitting || prompt.trim().length === 0}>{submitting ? "正在创建…" : "开始生成"}</button>
          : <Link className="button primary create-submit" href="/login?next=/create">登录后生成</Link>}</div>
      </form>

      <aside className="creation-preview" aria-labelledby="preview-title">
        <div className={`preview-stage${generation ? ` task-${generation.status}` : ""}`}><div className="preview-orbit" aria-hidden="true"><span /><span /><span /></div><div className="preview-copy"><span className="preview-kicker">{generation ? statusLabel(generation.status).toUpperCase() : "PREVIEW"}</span><h2 id="preview-title">{generation ? taskTitle(generation.status) : "画面将在这里生长"}</h2><p>{generation ? taskDescription(generation) : "提交后可以离开此页。任务会继续运行，并保存在“我的图片”中。"}</p>{generation?.images.length ? <div className="generated-links">{generation.images.map((image, index) => <Link key={image.id} href={`/gallery/${image.slug}`}>查看作品 {index + 1}</Link>)}</div> : null}</div></div>
        <div className="task-strip"><span className={`task-indicator${generation ? ` ${generation.status}` : ""}`} /><div><strong>{generation ? `${generation.workflowName} · ${statusLabel(generation.status)}` : "尚未创建任务"}</strong><small>{generation ? `任务 ${generation.id.slice(0, 8)} · ${generation.width}×${generation.height}` : "队列状态、耗时和取消操作将显示在这里"}</small></div>{generation && !terminal.has(generation.status) ? <button className="button task-cancel" type="button" onClick={() => void cancel()}>取消</button> : null}</div>
        <div className="privacy-assurance"><strong>平台级安全边界</strong><p>浏览器不会接触 Provider 密钥、内部工作流文件或对象存储凭据。</p></div>
      </aside>
    </div>
  </main>;
}

async function readJson(response: Response): Promise<unknown> {
  const body = response.headers.get("content-type")?.includes("application/json") ? await response.json() as unknown : undefined;
  if (response.ok) return body;
  const error = body && typeof body === "object" && !Array.isArray(body) ? (body as { error?: { message?: unknown } }).error : undefined;
  throw new Error(typeof error?.message === "string" ? error.message : "服务暂时不可用，请稍后重试。");
}
function statusLabel(status: GenerationView["status"]): string { return ({ pending: "排队中", running: "生成中", completed: "已完成", failed: "生成失败", cancelled: "已取消" })[status]; }
function taskTitle(status: GenerationView["status"]): string { return ({ pending: "灵感已进入队列", running: "画面正在生长", completed: "你的作品已经完成", failed: "这次创作没有完成", cancelled: "任务已取消" })[status]; }
function taskDescription(generation: GenerationView): string {
  if (generation.error) return generation.error.message;
  if (generation.status === "pending") return "平台正在安排合适的生成资源，你可以安全离开此页。";
  if (generation.status === "running") return generation.cancelRequested ? "已收到取消请求，正在安全停止任务。" : "Provider 正在生成并持久化图片，请稍候。";
  if (generation.status === "completed") return "图片已保存到对象存储，并加入你的创作历史。";
  return generation.status === "cancelled" ? "未消耗的预留积分会自动释放。" : "可以调整描述后重新尝试。";
}
