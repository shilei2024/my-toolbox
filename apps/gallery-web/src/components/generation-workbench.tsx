"use client";

import Link from "next/link";
import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { BillingSummary } from "@/lib/billing-types";
import type { GenerationMediaType, GenerationMode, GenerationPage, GenerationView, GenerationVisibility, GenerationWorkflow } from "@/lib/generation-types";

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
  const [mode, setMode] = useState<GenerationMode>("api");
  const [mediaType, setMediaType] = useState<GenerationMediaType>("image");
  const [inputImages, setInputImages] = useState<readonly { readonly name: string; readonly data: string }[]>([]);
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [size, setSize] = useState("1024x1024");
  const [aspect, setAspect] = useState("16:9");
  const [resolution, setResolution] = useState("720p");
  const [count, setCount] = useState(1);
  const [durationSeconds, setDurationSeconds] = useState(5);
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

  const refreshBilling = useCallback(async () => {
    try {
      const response = await fetch("/api/billing/summary", { cache: "no-store" });
      if (!response.ok) return;
      const body = await response.json() as BillingSummary;
      if (mountedRef.current) setBilling(body);
    } catch { /* Keep the last known balance when billing is temporarily unavailable. */ }
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
    if (item.mediaType === "video") {
      const aspectKey = nearestAspect(item.defaults.width, item.defaults.height);
      const alignedHeight = alignTo32(item.defaults.height);
      const resolutions = item.defaults.videoResolutions ?? VIDEO_RESOLUTIONS;
      const resolutionKey = resolutions.some((entry) => entry.height === alignedHeight) ? String(resolutions.find((entry) => entry.height === alignedHeight)?.key) : resolutions[0]?.key ?? "720p";
      setAspect(aspectKey);
      setResolution(resolutionKey);
      setSize(videoSizeFor(aspectKey, resolutionHeight(resolutionKey, resolutions)));
    } else {
      setSize(initialSize(item));
    }
    setCount(initialCount(item));
    setMediaType(item.mediaType ?? "image");
    setDurationSeconds(item.defaults.durationSeconds ?? item.durations?.[0] ?? 5);
    setVisibility(item.defaults.visibility ?? "public");
    setPromptVisibility(item.defaults.promptVisibility ?? "public");
  }, []);

  const applyComposerData = useCallback((data: Awaited<ReturnType<typeof fetchComposerData>>) => {
    setWorkflows(data.workflows);
    const initial = data.workflows.find((item) => (item.mediaType ?? "image") === "image" && item.mode === "api") ?? data.workflows[0]!;
    setMediaType(initial.mediaType ?? "image");
    setMode(initial.mode ?? "api");
    selectWorkflow(initial);
    setSession(data.session);
    setBilling(data.billing);
  }, [selectWorkflow]);

  const switchMode = useCallback((next: GenerationMode) => {
    setMode(next);
    const first = workflows.find((item) => (item.mediaType ?? "image") === mediaType && (item.mode ?? "workflow") === next);
    if (first) selectWorkflow(first); else setSelected("");
  }, [mediaType, selectWorkflow, workflows]);

  const switchMediaType = useCallback((next: GenerationMediaType) => {
    setMediaType(next);
    const firstInMode = workflows.find((item) => (item.mediaType ?? "image") === next && (item.mode ?? "workflow") === mode);
    const firstApi = workflows.find((item) => (item.mediaType ?? "image") === next && item.mode === "api");
    const first = firstInMode ?? firstApi ?? workflows.find((item) => (item.mediaType ?? "image") === next);
    if (first) {
      setMode(first.mode ?? "workflow");
      selectWorkflow(first);
    } else setSelected("");
  }, [mode, selectWorkflow, workflows]);

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

  const workflow = useMemo(() => workflows.find((item) => item.slug === selected && (item.mediaType ?? "image") === mediaType && (item.mode ?? "workflow") === mode), [mediaType, mode, workflows, selected]);
  const visibleWorkflows = useMemo(() => workflows.filter((item) => (item.mediaType ?? "image") === mediaType && (item.mode ?? "workflow") === mode), [mediaType, mode, workflows]);
  const h3Workflows = useMemo(() => visibleWorkflows.filter((item) => item.category === "MiniMax H3").sort((left, right) => (left.defaults.modeMeta?.key ?? "").localeCompare(right.defaults.modeMeta?.key ?? "")), [visibleWorkflows]);
  const otherWorkflows = useMemo(() => visibleWorkflows.filter((item) => item.category !== "MiniMax H3"), [visibleWorkflows]);
  const h3Selected = workflow?.category === "MiniMax H3";
  const h3Meta = workflow?.defaults.modeMeta;

  const addInputImages = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const activeMax = h3Meta?.maxImages ?? 3;
    const entries: { name: string; data: string }[] = [];
    for (const file of Array.from(files).slice(0, Math.max(0, activeMax - inputImages.length))) {
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) { setMessage("参考图仅支持 PNG/JPEG/WebP。"); continue; }
      if (file.size > 3 * 1024 * 1024) { setMessage("单张参考图不能超过 3MB。"); continue; }
      try {
        const raw = await readAsDataUrl(file);
        const data = await compressImage(raw);
        entries.push({ name: file.name, data });
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "参考图处理失败。");
      }
    }
    if (entries.length > 0) setInputImages((current) => [...current, ...entries].slice(0, activeMax));
  }, [h3Meta?.maxImages, inputImages.length]);

  const removeInputImage = useCallback((index: number) => {
    setInputImages((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }, []);
  const estimate = workflow ? (Number(workflow.creditCost) * count).toFixed(4).replace(/\.0+$/, "") : "—";
  const loggedIn = (session !== undefined && session.role !== "guest") || billing?.account !== undefined;

  async function submit() {
    if (!workflow || submitting || prompt.trim().length === 0) return;
    setSubmitting(true); setMessage("");
    const [width, height] = size.split("x").map(Number) as [number, number];
    try {
      const parameters = workflow.mediaType === "video" ? { durationSeconds } : {};
      const body: Record<string, unknown> = { workflowSlug: workflow.slug, prompt: prompt.trim(), negativePrompt: negativePrompt.trim(), width, height, count, visibility: workflow.mediaType === "video" ? "private" : visibility, promptVisibility: workflow.mediaType === "video" ? "hidden" : promptVisibility, creditTier, parameters };
      if (workflow.mediaType === "video" && h3Meta && h3Meta.maxImages > 0) {
        if (inputImages.length === 0) {
          setMessage("请先上传参考图。");
          setSubmitting(false);
          return;
        }
        body.inputImages = inputImages.map((image) => ({ name: image.name, data: image.data }));
      }
      const payload = JSON.stringify(body);
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
      void refreshBilling();
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
        else {
          void refreshRecent();
          void refreshBilling();
        }
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
      void refreshBilling();
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
      void refreshBilling();
    } catch (error) { setMessage(error instanceof Error ? error.message : "取消请求失败。"); }
  }

  function retryTask(item: GenerationView) {
    const target = workflows.find((entry) => entry.slug === item.workflowSlug);
    if (!target) {
      setMessage("该创作方式当前不可用，无法回填重试。");
      return;
    }
    setMode(target.mode ?? "workflow");
    setMediaType(target.mediaType ?? "image");
    setSelected(target.slug);
    setSize(`${item.width}x${item.height}`);
    if (target.mediaType === "video") {
      const aspectKey = nearestAspect(item.width, item.height);
      const resolutions = target.defaults.videoResolutions ?? VIDEO_RESOLUTIONS;
      setAspect(aspectKey);
      setResolution(resolutions.find((entry) => entry.height === alignTo32(item.height))?.key ?? resolutions[0]?.key ?? "720p");
    }
    setCount(item.count);
    setVisibility(item.visibility);
    setPromptVisibility(item.promptVisibility);
    setPrompt(item.prompt);
    setNegativePrompt(item.negativePrompt);
    setMessage("已回填上次参数，可修改后点击“开始生成”重新创作。");
  }

  return <main className="create-shell">
    <section className="create-heading" aria-labelledby="create-title">
      <div><p className="eyebrow"><span className="eyebrow-dot" />AI CREATION STUDIO</p><h1 id="create-title">把一个想法，变成<span>图片或视频。</span></h1><p>选择媒体与创作方式并描述画面。模型、供应商选择和故障降级由平台统一处理。</p></div>
      <div className="create-account-note" aria-label="账户状态"><span>当前账户</span><strong>{loggedIn ? (billing?.account ? `${billing.account.availableAmount} 可用积分` : "已登录") : "登录后可开始创作"}</strong><small>{loggedIn ? (billing?.account ? `${billing.account.reservedAmount} 积分正在任务中` : "积分余额暂时无法显示") : "与工具网站共用同一用户账户"}</small></div>
    </section>

    <div className="workbench-grid">
      <form className="composer-panel" aria-label="AI 图片和视频创作参数" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <div className="panel-heading"><div><span className="step-index">01</span><h2>选择创作方式</h2></div><span className="panel-hint">工作流与 API 模型分开选择</span></div>
        {loadState === "loading" ? <div className="workflow-loading">正在读取平台工作流…</div> : loadState === "error" ? <div className="inline-error-row"><div className="inline-error">{message}</div><button className="button" type="button" onClick={retryLoad}>重试</button></div> : <>
          <div className="creation-mode-tabs" role="tablist" aria-label="输出媒体类型">
            {(["image", "video"] as const).map((value) => <button key={value} type="button" role="tab" aria-selected={mediaType === value} className={`mode-tab${mediaType === value ? " active" : ""}`} onClick={() => switchMediaType(value)}>{value === "image" ? "生图" : "生视频"}<span className="mode-count">{workflows.filter((item) => (item.mediaType ?? "image") === value).length}</span></button>)}
          </div>
          <div className="creation-mode-tabs" role="tablist" aria-label="创作方式分类">
            {(["workflow", "api"] as const).map((value) => <button key={value} type="button" role="tab" aria-selected={mode === value} className={`mode-tab${mode === value ? " active" : ""}`} onClick={() => switchMode(value)}>{value === "workflow" ? "工作流" : "API 模型"}<span className="mode-count">{workflows.filter((item) => (item.mediaType ?? "image") === mediaType && item.mode === value).length}</span></button>)}
          </div>
          {visibleWorkflows.length === 0
            ? <div className="workflow-loading">该分类暂无可用方式，请切换分类或稍后再试。</div>
            : <div className="workflow-grid" role="radiogroup" aria-label={mode === "workflow" ? "工作流创作方式" : "API 模型创作方式"}>
              {otherWorkflows.map((item) => <label className={`workflow-option${selected === item.slug ? " selected" : ""}`} key={item.slug}><input type="radio" name="workflow" value={item.slug} checked={selected === item.slug} onChange={() => selectWorkflow(item)} /><span className="workflow-tone">{item.category}</span><strong>{item.name}</strong><small>{item.description}</small><span className="workflow-check">{selected === item.slug ? "✓ 已选" : ""}</span></label>)}
              {h3Workflows.length === 3 ? <label className={`workflow-option${h3Selected ? " selected" : ""}`}><input type="radio" name="workflow" value="minimax-h3-family" checked={h3Selected} onChange={() => selectWorkflow(h3Workflows[0]!)} /><span className="workflow-tone">MiniMax H3</span><strong>MiniMax H3 全能参考视频</strong><small>文生 / 单图 / 多图参考三合一：原生音视频，支持 4/5/8/10 秒。</small><span className="workflow-check">{h3Selected ? "✓ 已选" : ""}</span></label> : h3Workflows.map((item) => <label className={`workflow-option${selected === item.slug ? " selected" : ""}`} key={item.slug}><input type="radio" name="workflow" value={item.slug} checked={selected === item.slug} onChange={() => selectWorkflow(item)} /><span className="workflow-tone">{item.category}</span><strong>{item.name}</strong><small>{item.description}</small><span className="workflow-check">{selected === item.slug ? "✓ 已选" : ""}</span></label>)}
            </div>}
          {h3Selected && h3Workflows.length === 3 ? <>
            <div className="creation-mode-tabs" role="tablist" aria-label="MiniMax H3 生成模式">
              {h3Workflows.map((item) => <button key={item.slug} type="button" role="tab" aria-selected={selected === item.slug} className={`mode-tab${selected === item.slug ? " active" : ""}`} onClick={() => selectWorkflow(item)}>{item.defaults.modeMeta?.label ?? item.name}</button>)}
            </div>
            {h3Meta && h3Meta.maxImages > 0 ? <div className="reference-upload">
              <label className="reference-upload-field"><span>参考图（{inputImages.length}/{h3Meta.maxImages}）</span><input type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={(event) => { addInputImages(event.target.files); event.target.value = ""; }} /></label>
              {inputImages.length > 0
                ? <div className="reference-previews">{inputImages.map((image, index) => <div className="reference-thumb" key={`${image.name}-${index}`}><Image src={image.data} alt={`参考图 ${index + 1}`} width={84} height={84} unoptimized /><button type="button" onClick={() => removeInputImage(index)}>移除</button></div>)}</div>
                : <p className="panel-hint">单图模式上传 1 张；多图模式最多 3 张，提示词中用 @图片1 / @图片2 / @图片3 分别引用。</p>}
            </div> : null}
          </> : null}
        </>}

        <div className="composer-section"><div className="panel-heading compact"><div><span className="step-index">02</span><h2>描述你的画面</h2></div><span className="panel-hint">建议写清主体、环境、光线和质感</span></div>
          <label className="prompt-field"><span className="sr-only">画面描述</span><textarea required maxLength={2000} rows={7} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：夏日清晨的江南庭院，白墙黛瓦，薄雾穿过竹林，柔和自然光，安静而克制的电影质感……" /><small>{prompt.length} / 2000</small></label>
          <details className="advanced-prompt"><summary>添加不希望出现的内容</summary><label><span className="sr-only">负面描述</span><textarea maxLength={2000} rows={3} value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} placeholder="例如：模糊、文字、水印、过度锐化" /></label></details>
        </div>

        <div className="composer-section parameter-section"><div className="panel-heading compact"><div><span className="step-index">03</span><h2>画面设置</h2></div></div><div className="parameter-grid">
          <label><span>积分档位</span><select value={creditTier} onChange={(event) => setCreditTier(event.target.value as "free" | "member")}><option value="free">免费积分</option><option value="member">会员积分</option></select></label>
          {workflow?.mediaType === "video" ? <>
            <label><span>画面比例</span><select value={aspect} onChange={(event) => { const next = event.target.value; setAspect(next); const resolutions = workflow.defaults.videoResolutions ?? VIDEO_RESOLUTIONS; setSize(videoSizeFor(next, resolutionHeight(resolution, resolutions))); }}>{VIDEO_ASPECTS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
            <label><span>分辨率</span><select value={resolution} onChange={(event) => { const next = event.target.value; setResolution(next); const resolutions = workflow.defaults.videoResolutions ?? VIDEO_RESOLUTIONS; setSize(videoSizeFor(aspect, resolutionHeight(next, resolutions))); }}>{(workflow.defaults.videoResolutions ?? VIDEO_RESOLUTIONS).map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
            <label><span>视频时长</span><select value={durationSeconds} onChange={(event) => setDurationSeconds(Number(event.target.value))}>{(workflow.durations?.length ? workflow.durations : [5]).map((value) => <option key={value} value={value}>{value} 秒</option>)}</select></label>
            <label><span>作品可见性</span><select value="private" disabled><option value="private">仅自己可见</option></select></label>
          </> : <>
            <label><span>画面比例</span><select value={size} onChange={(event) => setSize(event.target.value)}>{workflow?.sizes?.length ? workflow.sizes.map((item) => { const key = sizeKey(item); return <option key={key} value={key}>{sizeLabel(key)}</option>; }) : <option value={size}>加载中…</option>}</select></label>
            <label><span>生成数量</span><select value={count} onChange={(event) => setCount(Number(event.target.value))}>{workflow ? countOptions(workflow).map((value) => <option key={value} value={value}>{value} 张</option>) : <option value={count}>加载中…</option>}</select></label>
            <label><span>作品可见性</span><select value={visibility} onChange={(event) => setVisibility(event.target.value as GenerationVisibility)}><option value="private">仅自己可见</option><option value="public">公开到画廊</option></select></label>
          </>}
        </div>{workflow?.mediaType === "video" ? <p className="panel-hint">视频暂只在本人创作记录和任务中心可见。</p> : <label className="prompt-privacy"><input type="checkbox" checked={promptVisibility === "hidden"} onChange={(event) => setPromptVisibility(event.target.checked ? "hidden" : "public")} />隐藏作品 Prompt</label>}</div>

        {message && loadState !== "error" ? <div className="inline-error" role="alert">{message}</div> : null}
        <div className="composer-submit"><div><span>本次预计</span><strong>{estimate} 积分</strong></div>{loggedIn
          ? <button className="button primary create-submit" type="submit" disabled={loadState !== "ready" || submitting || prompt.trim().length === 0 || (h3Meta !== undefined && h3Meta.maxImages > 0 && inputImages.length === 0)}>{submitting ? "正在创建…" : "开始生成"}</button>
          : <Link className="button primary create-submit" href="/login?next=/create">登录后生成</Link>}</div>
      </form>

      <aside className="creation-preview" aria-labelledby="preview-title">
        <div className={`preview-stage${generation ? ` task-${generation.status}` : ""}`}>
          {generation?.status === "completed" && generation.mediaType === "video" && generation.outputs[0] ? (
            <div className="preview-images" style={{ aspectRatio: `${generation.width} / ${generation.height}` }}><video src={generation.outputs[0].url} controls preload="metadata" playsInline aria-label="生成的视频" /></div>
          ) : generation?.status === "completed" && generation.images.length > 0 ? (
            <div className="preview-images" style={{ aspectRatio: `${generation.width} / ${generation.height}` }}>
              {generation.images.map((image, index) => {
                const url = previewUrls[image.slug];
                return <Link className={`preview-image${url ? "" : " pending"}`} key={image.id} href={`/gallery/${image.slug}`} aria-label={`查看作品 ${index + 1}`}>{url ? <Image src={url} alt={`作品 ${index + 1}`} width={generation.width} height={generation.height} sizes="(max-width: 900px) 100vw, 44vw" unoptimized /> : <span>作品 {index + 1}</span>}</Link>;
              })}
            </div>
          ) : (<><div className="preview-orbit" aria-hidden="true"><span /><span /><span /></div><div className="preview-copy">{generation ? <span className="preview-kicker">{statusLabel(generation.status).toUpperCase()}</span> : null}<h2 id="preview-title">{generation ? statusLabel(generation.status) : "生成结果将显示在这里"}</h2><p>{generation ? taskDescription(generation) : ""}</p></div></>)}
          {generation?.images.length ? <div className="generated-links">{generation.images.map((image, index) => <Link key={image.id} href={`/gallery/${image.slug}`}>查看作品 {index + 1}</Link>)}</div> : null}
        </div>
        <div className="task-strip"><span className={`task-indicator${generation ? ` ${generation.status}` : ""}`} /><div><strong>{generation ? `${generation.workflowName} · ${statusLabel(generation.status)}` : "尚未创建任务"}</strong><small>{generation ? `任务 ${generation.id.slice(0, 8)} · ${generation.width}×${generation.height}` : "队列状态、耗时和取消操作将显示在这里"}</small></div>{generation && !terminal.has(generation.status) && !(generation.mediaType === "video" && generation.status === "running") ? <button className="button task-cancel" type="button" onClick={() => void cancel()}>取消</button> : null}</div>
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
              <span className="recent-thumb">{firstUrl ? <Image src={firstUrl} alt="" width={96} height={64} sizes="96px" unoptimized /> : <span>{item.status === "failed" ? "失败" : item.mediaType === "video" && item.outputs.length ? "视频" : item.images.length ? `${item.images.length} 张` : "…"}</span>}</span>
              <span className="recent-main"><strong>{item.workflowName}</strong><small>{promptSummary(item.prompt)}</small></span>
              <span className="recent-meta"><em>{statusLabel(item.status)}</em><time>{formatTime(item.createdAt)}</time></span>
            </button>
            <div className="recent-actions">
              {!terminal.has(item.status) && !(item.mediaType === "video" && item.status === "running") ? <button className="button recent-action" type="button" onClick={() => void cancelTask(item)}>取消</button> : null}
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

const VIDEO_ASPECTS: readonly { readonly key: string; readonly label: string; readonly width: number; readonly height: number }[] = [
  { key: "1:1", label: "1:1 方形", width: 1, height: 1 },
  { key: "4:3", label: "4:3 横图", width: 4, height: 3 },
  { key: "3:4", label: "3:4 竖图", width: 3, height: 4 },
  { key: "16:9", label: "16:9 横图", width: 16, height: 9 },
  { key: "9:16", label: "9:16 竖图", width: 9, height: 16 },
  { key: "21:9", label: "21:9 超宽", width: 21, height: 9 },
] as const;

const VIDEO_RESOLUTIONS: readonly { readonly key: string; readonly label: string; readonly height: number }[] = [
  { key: "480p", label: "480p", height: 480 },
  { key: "720p", label: "720p 高清", height: 704 },
  { key: "1080p", label: "1080p 全高清", height: 1088 },
  { key: "2K", label: "2K", height: 1152 },
] as const;

function alignTo32(value: number): number {
  return Math.max(256, Math.round(value / 32) * 32);
}

function nearestAspect(width: number, height: number): string {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return "16:9";
  const ratio = width / height;
  let best = VIDEO_ASPECTS[3]!;
  let bestDelta = Number.POSITIVE_INFINITY;
  for (const entry of VIDEO_ASPECTS) {
    const delta = Math.abs(ratio - entry.width / entry.height);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = entry;
    }
  }
  return best.key;
}

function resolutionHeight(key: string, resolutions: readonly { readonly key: string; readonly height: number }[]): number {
  return resolutions.find((entry) => entry.key === key)?.height ?? 704;
}

function videoSizeFor(aspectKey: string, height: number): string {
  const aspect = VIDEO_ASPECTS.find((entry) => entry.key === aspectKey) ?? VIDEO_ASPECTS[3]!;
  const width = alignTo32(height * aspect.width / aspect.height);
  return `${width}x${height}`;
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(new Error("读取参考图失败。"));
    reader.readAsDataURL(file);
  });
}

async function compressImage(dataUrl: string): Promise<string> {
  const image = new window.Image();
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error("参考图解析失败。"));
    image.src = dataUrl;
  });
  const maxSide = 1024;
  const scale = Math.min(1, maxSide / Math.max(image.width, image.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.width * scale));
  canvas.height = Math.max(1, Math.round(image.height * scale));
  const context = canvas.getContext("2d");
  if (!context) return dataUrl;
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  const webp = canvas.toDataURL("image/webp", 0.85);
  return webp.startsWith("data:image/webp") ? webp : canvas.toDataURL("image/jpeg", 0.85);
}
