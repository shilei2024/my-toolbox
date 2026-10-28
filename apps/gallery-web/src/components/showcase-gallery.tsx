"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { GalleryFacets, GalleryImageDetail, GalleryImageSummary, GalleryPageData } from "@/lib/gallery-types";
import { buildJustifiedRows, clamp } from "@/lib/justified-layout";

type MediaFilter = "" | "image" | "video";
type Orientation = "" | "portrait" | "square" | "landscape";
type SortMode = "latest" | "popular";

interface ViewerInfo {
  readonly role: "guest" | "user" | "admin";
  readonly displayName?: string;
}

interface ShowcaseLinks {
  readonly login: string;
  readonly create: string;
  readonly admin?: string;
  readonly mainSite?: string;
}

interface ShowcaseGalleryProps {
  readonly initialPage: GalleryPageData;
  readonly initialFacets: GalleryFacets;
  readonly initialError?: string;
  readonly viewer: ViewerInfo;
  readonly links: ShowcaseLinks;
  readonly initialFilters?: {
    readonly query?: string;
    readonly mediaType?: MediaFilter;
    readonly model?: string;
    readonly orientation?: Orientation;
    readonly sort?: SortMode;
  };
}

const EMPTY_FACETS: GalleryFacets = { total: 0, media: { image: 0, video: 0 }, workflows: [] };
const PAGE_SIZE = 24;
const GRID_GAP = 16;

export function ShowcaseGallery({ initialPage, initialFacets, initialError, viewer, links, initialFilters }: ShowcaseGalleryProps) {
  const [items, setItems] = useState<readonly GalleryImageSummary[]>(initialPage.items);
  const [nextCursor, setNextCursor] = useState(initialPage.nextCursor);
  const [query, setQuery] = useState(initialFilters?.query ?? "");
  const [mediaType, setMediaType] = useState<MediaFilter>(initialFilters?.mediaType ?? "");
  const [model, setModel] = useState(initialFilters?.model ?? "");
  const [orientation, setOrientation] = useState<Orientation>(initialFilters?.orientation ?? "");
  const [sort, setSort] = useState<SortMode>(initialFilters?.sort ?? "latest");
  const [facets, setFacets] = useState<GalleryFacets>(initialFacets ?? EMPTY_FACETS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(initialError);
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const [toast, setToast] = useState<string>();
  const requestSequence = useRef(0);
  const controllerRef = useRef<AbortController | undefined>(undefined);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const [gridWidth, setGridWidth] = useState(1200);
  const authenticated = viewer.role !== "guest";

  useEffect(() => () => controllerRef.current?.abort(), []);

  useEffect(() => {
    const node = gridRef.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width && width > 0) setGridWidth(Math.round(width));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast((current) => (current === message ? undefined : current)), 1800);
  }, []);

  const load = useCallback(async (options: { append?: boolean; cursor?: string; filters?: { query?: string; mediaType?: MediaFilter; model?: string; orientation?: Orientation; sort?: SortMode } } = {}) => {
    const next = {
      query: options.filters?.query ?? query,
      mediaType: options.filters?.mediaType ?? mediaType,
      model: options.filters?.model ?? model,
      orientation: options.filters?.orientation ?? orientation,
      sort: options.filters?.sort ?? sort,
    };
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError(undefined);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (next.query.trim()) params.set("q", next.query.trim());
    if (next.mediaType) params.set("mediaType", next.mediaType);
    if (next.model) params.set("workflow", next.model);
    if (next.orientation) params.set("orientation", next.orientation);
    if (next.sort === "popular") params.set("sort", "popular");
    if (options.cursor) params.set("cursor", options.cursor);
    try {
      const response = await fetch(`/api/gallery?${params.toString()}`, { headers: { Accept: "application/json" }, signal: controller.signal });
      const body = await response.json() as GalleryPageData & { error?: { message?: string } };
      if (!response.ok) throw new Error(body.error?.message || "暂时无法读取作品");
      if (sequence !== requestSequence.current) return;
      setItems((current) => (options.append ? [...current, ...body.items] : body.items));
      setNextCursor(body.nextCursor);
      syncLocation(next, options.cursor);
    } catch (caught) {
      if (controller.signal.aborted || sequence !== requestSequence.current) return;
      setError(caught instanceof Error ? caught.message : "暂时无法读取作品");
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [query, mediaType, model, orientation, sort]);

  // 首次加载失败时（服务暂不可用）静默重试一次聚合面板，避免顶部筛选空白。
  useEffect(() => {
    if (initialFacets && initialFacets.workflows.length > 0) return;
    let active = true;
    fetch("/api/gallery/facets", { headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() as Promise<GalleryFacets> : undefined))
      .then((value) => { if (active && value) setFacets(value); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [initialFacets]);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void load({ filters: { query } });
  };

  const changeMedia = (value: MediaFilter) => {
    setMediaType(value);
    void load({ filters: { mediaType: value } });
  };
  const changeModel = (value: string) => {
    setModel(value);
    void load({ filters: { model: value } });
  };
  const changeOrientation = (value: Orientation) => {
    setOrientation(value);
    void load({ filters: { orientation: value } });
  };
  const changeSort = (value: SortMode) => {
    setSort(value);
    void load({ filters: { sort: value } });
  };

  const openViewer = (index: number) => setViewerIndex(index);
  const closeViewer = () => setViewerIndex(null);

  const rows = useMemo(() => buildJustifiedRows(items, gridWidth, gridWidth < 640 ? 190 : gridWidth < 960 ? 220 : gridWidth < 1280 ? 250 : 280, GRID_GAP), [items, gridWidth]);

  return (
    <div className="sc-root">
      <header className="sc-topbar">
        <div className="sc-topbar-inner">
          <Link className="sc-brand" href="/gallery" aria-label="Mavis 灵感画廊首页">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/brand/mavis-mark.svg" alt="" width={30} height={30} />
            <span className="sc-brand-word">Mavis<small>灵感画廊</small></span>
            <span className="sc-brand-tag">作品集</span>
          </Link>
          <form className="sc-search" role="search" onSubmit={submitSearch}>
            <span className="sc-visually-hidden">搜索作品</span>
            <SearchIcon />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索题材、风格或提示词"
              maxLength={120}
              enterKeyHint="search"
            />
          </form>
          <div className="sc-topbar-end">
            {links.mainSite ? <a className="sc-pill sc-pill--small sc-hide-sm" href={links.mainSite}>工具箱</a> : null}
            {viewer.role === "admin" && links.admin ? <a className="sc-pill sc-pill--small" href={links.admin}>后台</a> : null}
            {authenticated
              ? <span className="sc-account-name" title={viewer.displayName}>{viewer.displayName || "我的账号"}</span>
              : <Link className="sc-pill sc-pill--small" href={links.login}>登录</Link>}
            <Link className="sc-pill sc-pill--small sc-pill--accent" href={links.create}>开始创作</Link>
          </div>
        </div>
      </header>

      <section className="sc-hero" aria-labelledby="sc-hero-title">
        <div className="sc-hero-inner">
          <div className="sc-hero-copy">
            <h1 id="sc-hero-title">每件作品都附<mark>完整提示词</mark></h1>
            <p className="sc-hero-lede">AI 图像与视频作品，公开即附提示词。复制提示词带回工作台，或登录后直接生成同款。</p>
          </div>
          <div className="sc-hero-actions">
            <Link className="sc-pill sc-pill--accent sc-pill--large" href={links.create}>开始创作</Link>
            <a className="sc-pill sc-pill--ghost sc-pill--large" href="#works">浏览作品</a>
          </div>
        </div>
        <FilmStrip items={items.slice(0, 14)} />
      </section>

      <div className="sc-page" id="works">
        <nav className="sc-channels" aria-label="作品频道">
          <div className="sc-channel-tabs">
            <ChannelTab label="全部作品" active={mediaType === ""} count={facets.total} onClick={() => changeMedia("")} />
            <ChannelTab label="图片" active={mediaType === "image"} count={facets.media.image} onClick={() => changeMedia("image")} />
            <ChannelTab label="视频" active={mediaType === "video"} count={facets.media.video} onClick={() => changeMedia("video")} />
          </div>
        </nav>

        <section className="sc-toolbar" aria-label="筛选与排序">
          <div className="sc-filters">
            <div className="sc-filter-row">
              <span className="sc-filter-label">模型</span>
              <div className="sc-chips" role="group" aria-label="模型">
                <button className="sc-chip sc-chip--model" type="button" aria-pressed={model === ""} onClick={() => changeModel("")}>全部</button>
                {facets.workflows.map((workflow) => (
                  <button key={workflow.name} className="sc-chip sc-chip--model" type="button" aria-pressed={model === workflow.name} onClick={() => changeModel(workflow.name)}>
                    {workflow.name}<span className="sc-visually-hidden">{` 共 ${workflow.count} 件`}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="sc-filter-row">
              <span className="sc-filter-label">方向</span>
              <div className="sc-chips" role="group" aria-label="图片方向">
                {([["", "全部"], ["portrait", "竖图"], ["square", "方图"], ["landscape", "横图"]] as const).map(([value, label]) => (
                  <button key={label} className="sc-chip" type="button" aria-pressed={orientation === value} onClick={() => changeOrientation(value)}>{label}</button>
                ))}
              </div>
            </div>
          </div>
          <div className="sc-toolbar-end">
            <p className="sc-count" aria-live="polite">{loading ? "正在读取…" : `${items.length} 件作品`}</p>
            <div className="sc-sort" role="group" aria-label="排序">
              <button type="button" aria-pressed={sort === "latest"} onClick={() => changeSort("latest")}>最新</button>
              <button type="button" aria-pressed={sort === "popular"} onClick={() => changeSort("popular")}>最多收藏</button>
            </div>
          </div>
        </section>

        <main className="sc-works" aria-busy={loading}>
          {loading && items.length === 0 ? <GridSkeleton /> : null}
          {!loading && error ? (
            <StateMessage mark="!" title="暂时无法读取作品" description={error} />
          ) : null}
          {!loading && !error && items.length === 0 ? (
            <StateMessage mark="0" title="还没有匹配的作品" description="换一个关键词或清空筛选，看看其他作品。" />
          ) : null}
          <div className="sc-grid" ref={gridRef} style={{ display: rows.length > 0 ? "block" : "none" }}>
            {rows.map((row, index) => (
              <div key={index} style={{ display: "flex", gap: `${GRID_GAP}px`, marginBottom: "30px", alignItems: "flex-start" }}>
                {row.tiles.map((tile) => (
                  <ArtworkTile
                    key={tile.item.id}
                    item={tile.item}
                    width={row.height * tile.ratio}
                    onOpen={() => openViewer(items.findIndex((entry) => entry.id === tile.item.id))}
                  />
                ))}
              </div>
            ))}
          </div>
          {nextCursor && sort === "latest" ? (
            <div className="sc-more">
              <button className="sc-pill" type="button" disabled={loading} onClick={() => void load({ append: true, cursor: nextCursor })}>
                {loading ? "加载中…" : "加载更多"}
              </button>
            </div>
          ) : null}
          {!nextCursor && items.length > 0 ? <p className="sc-end">已经到底了 · 共 {items.length} 件作品</p> : null}
        </main>

        <footer className="sc-footer">
          <p>作品版权归创作者所有。提示词与参数用于创作参考，生成结果以实际模型为准。</p>
          <p><Link href={links.create}>开始创作</Link> · <Link href="/gallery">全部作品</Link></p>
        </footer>
      </div>

      {viewerIndex !== null && items[viewerIndex] ? (
        <ArtworkViewer
          items={items}
          index={viewerIndex}
          authenticated={authenticated}
          createHref={links.create}
          onClose={closeViewer}
          onNavigate={setViewerIndex}
          onToast={showToast}
        />
      ) : null}

      {toast ? <div className="sc-toast" role="status">{toast}</div> : null}
    </div>
  );
}

function ChannelTab({ label, count, active, onClick }: { readonly label: string; readonly count?: number; readonly active: boolean; readonly onClick: () => void }) {
  return (
    <button className="sc-channel" type="button" aria-pressed={active} onClick={onClick}>
      {label}{count !== undefined && count > 0 ? <em>{count}</em> : null}
    </button>
  );
}

function FilmStrip({ items }: { readonly items: readonly GalleryImageSummary[] }) {
  if (items.length === 0) return null;
  // 同一批作品复制两份，让 translateX(-50%) 的无限滚动无缝衔接。
  const track = [...items, ...items];
  return (
    <div className="sc-strip" aria-hidden="true">
      <div className="sc-strip-track">
        {track.map((item, index) => (
          <div key={`${item.id}-${index}`} className="sc-strip-tile" style={{ "--ratio": String(clamp(item.width / item.height, 0.55, 1.6)) } as React.CSSProperties}>
            {isVideo(item) ? (
              <video src={`${item.asset.url}#t=0.1`} muted playsInline preload="metadata" />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={item.asset.url} alt="" loading="lazy" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ArtworkTile({ item, width, onOpen }: { readonly item: GalleryImageSummary; readonly width: number; readonly onOpen: () => void }) {
  return (
    <button className="sc-tile" type="button" style={{ width: `${Math.max(width, 120)}px` }} onClick={onOpen} aria-label={`查看作品：${item.title || "未命名作品"}`}>
      <div className="sc-tile-media">
        {isVideo(item) ? (
          <video src={`${item.asset.url}#t=0.1`} muted playsInline preload="metadata" onMouseEnter={(event) => { void event.currentTarget.play().catch(() => undefined); }} onMouseLeave={(event) => { const video = event.currentTarget; video.pause(); video.currentTime = 0.1; }} />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={item.asset.url} alt={item.title || "AI 生成作品"} loading="lazy" width={item.asset.width} height={item.asset.height} />
        )}
        {isVideo(item) ? <span className="sc-tile-play" aria-hidden="true"><PlayIcon /></span> : null}
      </div>
      <span className="sc-tile-caption">
        <span className="sc-tile-title">{item.title || "未命名作品"}</span>
        <span className="sc-tile-meta">{item.workflowName}{item.durationSeconds ? ` · ${item.durationSeconds}s` : ""}</span>
      </span>
    </button>
  );
}

function ArtworkViewer({ items, index, authenticated, createHref, onClose, onNavigate, onToast }: {
  readonly items: readonly GalleryImageSummary[];
  readonly index: number;
  readonly authenticated: boolean;
  readonly createHref: string;
  readonly onClose: () => void;
  readonly onNavigate: (index: number) => void;
  readonly onToast: (message: string) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const item = items[index]!;
  const [detail, setDetail] = useState<GalleryImageDetail>();
  const [detailError, setDetailError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const cacheRef = useRef(new Map<string, GalleryImageDetail>());

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  useEffect(() => {
    let active = true;
    const cached = cacheRef.current.get(item.slug);
    if (cached) { setDetail(cached); setDetailError(undefined); return; }
    setDetail(undefined);
    setDetailError(undefined);
    fetch(`/api/gallery/${encodeURIComponent(item.slug)}`, { headers: { Accept: "application/json" } })
      .then(async (response) => {
        const body = await response.json() as GalleryImageDetail & { error?: { message?: string } };
        if (!response.ok) throw new Error(body.error?.message || "暂时无法读取作品详情");
        cacheRef.current.set(item.slug, body);
        return body;
      })
      .then((value) => { if (active) setDetail(value); })
      .catch((caught: unknown) => { if (active) setDetailError(caught instanceof Error ? caught.message : "暂时无法读取作品详情"); });
    return () => { active = false; };
  }, [item.slug]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft" && index > 0) { event.preventDefault(); onNavigate(index - 1); }
      if (event.key === "ArrowRight" && index < items.length - 1) { event.preventDefault(); onNavigate(index + 1); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [index, items.length, onNavigate]);

  const related = items.filter((entry) => entry.id !== item.id && entry.workflowName === item.workflowName).slice(0, 4);
  const prompt = detail?.prompt;

  async function copyPrompt() {
    if (!prompt) return;
    try {
      await navigator.clipboard.writeText(prompt);
      onToast("提示词已复制");
    } catch {
      onToast("复制失败，请手动选择文本");
    }
  }

  async function toggleFavorite() {
    if (!authenticated || saving) return;
    setSaving(true);
    try {
      const response = await fetch(`/api/images/${item.id}/favorite`, { method: detail?.viewerHasFavorited ?? item.viewerHasFavorited ? "DELETE" : "PUT" });
      const result = await response.json() as { active?: boolean; count?: number };
      if (response.ok && typeof result.active === "boolean" && typeof result.count === "number") {
        setDetail((current) => (current ? { ...current, viewerHasFavorited: result.active!, favoriteCount: result.count! } : current));
        onToast(result.active ? "已收藏" : "已取消收藏");
      }
    } finally {
      setSaving(false);
    }
  }

  async function toggleLike() {
    if (!authenticated || saving) return;
    setSaving(true);
    try {
      const response = await fetch(`/api/images/${item.id}/like`, { method: detail?.viewerHasLiked ?? item.viewerHasLiked ? "DELETE" : "PUT" });
      const result = await response.json() as { active?: boolean; count?: number };
      if (response.ok && typeof result.active === "boolean" && typeof result.count === "number") {
        setDetail((current) => (current ? { ...current, viewerHasLiked: result.active!, likeCount: result.count! } : current));
        onToast(result.active ? "已点赞" : "已取消点赞");
      }
    } finally {
      setSaving(false);
    }
  }

  async function download() {
    const response = await fetch(`/api/images/${item.id}/download`, { method: "POST" });
    const body = await response.json() as { url?: string };
    if (response.ok && body.url) window.open(body.url, "_blank", "noopener");
    else onToast("下载暂时不可用");
  }

  return (
    <dialog
      className="sc-viewer"
      ref={dialogRef}
      aria-labelledby="sc-viewer-title"
      onClose={onClose}
      onClick={(event) => { if (event.target === event.currentTarget) dialogRef.current?.close(); }}
    >
      <div className="sc-stage">
        <div className="sc-stage-media">
          {isVideo(item) ? (
            <video key={item.id} src={item.asset.url} controls autoPlay muted loop playsInline aria-label={item.title || "AI 生成视频"} />
          ) : detail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={item.id} src={detail.asset.url} alt={item.title || "AI 生成作品"} />
          ) : (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img key={item.id} src={item.asset.url} alt={item.title || "AI 生成作品"} />
              {!detailError ? <div className="sc-stage-loading" aria-hidden="true" /> : null}
            </>
          )}
        </div>
        {index > 0 ? (
          <button className="sc-stage-nav sc-stage-nav--prev" type="button" aria-label="上一个作品" onClick={() => onNavigate(index - 1)}><ChevronLeft /></button>
        ) : null}
        {index < items.length - 1 ? (
          <button className="sc-stage-nav sc-stage-nav--next" type="button" aria-label="下一个作品" onClick={() => onNavigate(index + 1)}><ChevronRight /></button>
        ) : null}
      </div>

      <div className="sc-panel">
        <div className="sc-panel-scroll">
          <h2 id="sc-viewer-title">{item.title || "未命名作品"}</h2>
          <div className="sc-panel-body">
            <p className="sc-byline">
              <span>{item.creator?.displayName || "Mavis 社区"}</span>
              <span>{formatDate(item.publishedAt)}</span>
            </p>
            <div className="sc-facts">
              <span className="sc-fact sc-fact--model">{item.workflowName}</span>
              <span className="sc-fact">{item.width} × {item.height}</span>
              {isVideo(item) && item.durationSeconds ? <span className="sc-fact">{item.durationSeconds}s</span> : null}
              <span className="sc-fact">{item.favoriteCount} 收藏</span>
              <span className="sc-fact">{item.likeCount} 赞</span>
            </div>
            {detail?.description ? <p className="sc-about">{detail.description}</p> : null}

            <section className="sc-block">
              <div className="sc-block-head">
                <h3>提示词</h3>
                {prompt ? <button className="sc-copy" type="button" onClick={() => void copyPrompt()}>复制提示词</button> : null}
              </div>
              {prompt ? (
                <pre className="sc-prompt" tabIndex={0}>{prompt}</pre>
              ) : (
                <p className="sc-about">{detailError ? detailError : detail ? "创作者已隐藏提示词。" : "正在读取提示词…"}</p>
              )}
            </section>

            {detail?.negativePrompt ? (
              <section className="sc-block">
                <h3>负面提示词</h3>
                <pre className="sc-prompt" style={{ minHeight: 72 }}>{detail.negativePrompt}</pre>
              </section>
            ) : null}

            {detail && (detail.seed || detail.sampler || detail.steps !== undefined || detail.cfg !== undefined || detail.model) ? (
              <section className="sc-block">
                <h3>生成参数</h3>
                <dl className="sc-params">
                  {detail.model ? <><dt>模型</dt><dd>{detail.model}</dd></> : null}
                  {detail.providerCode ? <><dt>Provider</dt><dd>{detail.providerCode}</dd></> : null}
                  {detail.seed ? <><dt>Seed</dt><dd>{detail.seed}</dd></> : null}
                  {detail.sampler ? <><dt>采样器</dt><dd>{detail.sampler}</dd></> : null}
                  {detail.steps !== undefined ? <><dt>Steps</dt><dd>{detail.steps}</dd></> : null}
                  {detail.cfg !== undefined ? <><dt>CFG</dt><dd>{detail.cfg}</dd></> : null}
                </dl>
              </section>
            ) : null}

            {item.tags.length > 0 ? (
              <section className="sc-block">
                <h3>标签</h3>
                <div className="sc-tags">
                  {item.tags.map((tag) => <Link key={tag} className="sc-tag" href={`/gallery?tag=${encodeURIComponent(tag)}`}>{tag}</Link>)}
                </div>
              </section>
            ) : null}

            <div className="sc-actions">
              <button className="sc-pill" type="button" disabled={!authenticated || saving} onClick={() => void toggleFavorite()} aria-pressed={detail?.viewerHasFavorited ?? item.viewerHasFavorited}>
                {(detail?.viewerHasFavorited ?? item.viewerHasFavorited) ? "已收藏" : "收藏"}
              </button>
              <button className="sc-pill" type="button" disabled={!authenticated || saving} onClick={() => void toggleLike()} aria-pressed={detail?.viewerHasLiked ?? item.viewerHasLiked}>
                {(detail?.viewerHasLiked ?? item.viewerHasLiked) ? "已赞" : "点赞"}
              </button>
              <button className="sc-pill" type="button" onClick={() => void download()}>下载原图</button>
              <Link className="sc-pill sc-pill--accent" href={createHref}>前往创作台</Link>
            </div>

            {related.length > 0 ? (
              <section className="sc-related">
                <h3>相似作品</h3>
                <div className="sc-related-grid">
                  {related.map((entry) => (
                    <button key={entry.id} className="sc-related-card" type="button" onClick={() => onNavigate(items.findIndex((value) => value.id === entry.id))}>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={entry.asset.url} alt={entry.title || "相似作品"} loading="lazy" />
                      <span>{entry.title || "未命名作品"}</span>
                    </button>
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        </div>
        <button className="sc-close" type="button" aria-label="关闭" onClick={() => dialogRef.current?.close()}><CloseIcon /></button>
      </div>
    </dialog>
  );
}

function GridSkeleton() {
  return (
    <div className="sc-skeleton" aria-label="正在加载作品">
      {[240, 320, 280, 360, 260, 300].map((height, index) => (
        <div key={index} className="sc-skeleton-tile" style={{ width: `${160 + (index % 3) * 60}px`, height: `${height}px` }} />
      ))}
    </div>
  );
}

function StateMessage({ mark, title, description }: { readonly mark: string; readonly title: string; readonly description: string }) {
  return (
    <div className="sc-state">
      <div className="sc-state-mark" aria-hidden="true">{mark}</div>
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  );
}

function isVideo(item: GalleryImageSummary): boolean {
  return item.mediaType === "video" || item.asset.mimeType.startsWith("video/");
}

function formatDate(value: string): string {
  try {
    return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric" }).format(new Date(value));
  } catch {
    return "";
  }
}

function syncLocation(filters: { query: string; mediaType: MediaFilter; model: string; orientation: Orientation; sort: SortMode }, cursor?: string): void {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams();
  if (filters.query.trim()) params.set("q", filters.query.trim());
  if (filters.mediaType) params.set("mediaType", filters.mediaType);
  if (filters.model) params.set("workflow", filters.model);
  if (filters.orientation) params.set("orientation", filters.orientation);
  if (filters.sort === "popular") params.set("sort", "popular");
  if (cursor) params.set("cursor", cursor);
  const next = params.toString();
  window.history.replaceState(null, "", next ? `/gallery?${next}` : "/gallery");
}

function SearchIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2.4" /><path d="m20 20-4.2-4.2" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" /></svg>;
}
function PlayIcon() { return <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 1.2v9.6L10.4 6z" /></svg>; }
function ChevronLeft() { return <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function ChevronRight() { return <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20"><path d="m9 5 7 7-7 7" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function CloseIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" /></svg>; }
