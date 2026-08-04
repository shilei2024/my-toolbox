"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import type { GalleryImageSummary, GalleryPageData } from "@/lib/gallery-types";

type ViewMode = "masonry" | "grid" | "compact";
type Orientation = "" | "portrait" | "square" | "landscape";

const viewLabels: Record<ViewMode, string> = { masonry: "瀑布流", grid: "等宽网格", compact: "紧凑" };

export function GalleryExplorer({ initialPage, initialError, authenticated }: { initialPage: GalleryPageData; initialError?: string; authenticated: boolean }) {
  const [view, setView] = useState<ViewMode>("masonry");
  const [items, setItems] = useState<readonly GalleryImageSummary[]>(initialPage.items);
  const [nextCursor, setNextCursor] = useState(initialPage.nextCursor);
  const [query, setQuery] = useState("");
  const [orientation, setOrientation] = useState<Orientation>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(initialError);
  const [tweaksOpen, setTweaksOpen] = useState(false);

  async function loadPage(options: { replace: boolean; cursor?: string } = { replace: true }) {
    setLoading(true);
    setError(undefined);
    const params = new URLSearchParams({ limit: "24" });
    if (query.trim()) params.set("q", query.trim());
    if (orientation) params.set("orientation", orientation);
    if (options.cursor) params.set("cursor", options.cursor);
    try {
      const response = await fetch(`/api/gallery?${params}`, { headers: { Accept: "application/json" } });
      const body = await response.json() as GalleryPageData & { error?: { message?: string } };
      if (!response.ok) throw new Error(body.error?.message || "暂时无法读取作品");
      setItems((current) => options.replace ? body.items : [...current, ...body.items]);
      setNextCursor(body.nextCursor);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "暂时无法读取作品");
    } finally {
      setLoading(false);
    }
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadPage({ replace: true });
  }

  function updateFavorite(imageId: string, result: { active: boolean; count: number }) {
    setItems((current) => current.map((item) => item.id === imageId ? { ...item, viewerHasFavorited: result.active, favoriteCount: result.count } : item));
  }

  return (
    <>
      <section className="gallery-panel" aria-label="作品画廊">
        <form className="toolbar" onSubmit={submitSearch}>
          <div className="toolbar-group gallery-search-group">
            <input className="search-field" type="search" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="搜索作品" placeholder="搜索标题、描述或公开提示词" maxLength={120} />
            <select className="filter-select" value={orientation} onChange={(event) => setOrientation(event.target.value as Orientation)} aria-label="筛选图片方向">
              <option value="">全部方向</option>
              <option value="portrait">竖图</option>
              <option value="square">方图</option>
              <option value="landscape">横图</option>
            </select>
            <button className="button" type="submit" disabled={loading}>搜索</button>
          </div>
          <ViewSelector value={view} onChange={setView} />
        </form>

        {loading && items.length === 0 && <GallerySkeleton />}
        {!loading && error && <StateMessage mark="!" title="暂时无法读取作品" description={error} error />}
        {!loading && !error && items.length === 0 && <StateMessage mark="0" title="还没有公开作品" description="公开且审核通过的作品会出现在这里。" />}
        {items.length > 0 && (
          <>
            <div className={`gallery-grid ${view}`}>
              {items.map((item) => <ArtworkCard key={item.id} item={item} authenticated={authenticated} onFavorite={updateFavorite} />)}
            </div>
            {nextCursor && (
              <div className="load-more-row">
                <button className="button" type="button" disabled={loading} onClick={() => void loadPage({ replace: false, cursor: nextCursor })}>
                  {loading ? "加载中…" : "加载更多"}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      <aside className={`tweaks-panel ${tweaksOpen ? "" : "closed"}`} aria-label="画廊布局设置">
        <button className="tweaks-toggle" type="button" onClick={() => setTweaksOpen((open) => !open)}>{tweaksOpen ? "收起布局设置" : "切换画廊布局"}</button>
        {tweaksOpen && <div className="tweaks-content"><span className="tweak-label">布局密度</span><ViewSelector value={view} onChange={setView} /></div>}
      </aside>
    </>
  );
}

export function ArtworkCard({ item, authenticated, onFavorite }: { item: GalleryImageSummary; authenticated: boolean; onFavorite?: (imageId: string, result: { active: boolean; count: number }) => void }) {
  const [saving, setSaving] = useState(false);
  async function toggleFavorite() {
    if (!authenticated || saving) return;
    setSaving(true);
    try {
      const response = await fetch(`/api/images/${item.id}/favorite`, { method: item.viewerHasFavorited ? "DELETE" : "PUT" });
      const result = await response.json() as { active?: boolean; count?: number };
      if (response.ok && typeof result.active === "boolean" && typeof result.count === "number") onFavorite?.(item.id, { active: result.active, count: result.count });
    } finally { setSaving(false); }
  }
  return (
    <article className="art-card">
      <Link href={`/gallery/${item.slug}`} className="art-link" aria-label={item.title || "查看未命名作品"}>
        {/* The backend validates every asset URL against the configured COS/CDN allowlist. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="real-art" src={item.asset.url} width={item.asset.width} height={item.asset.height} alt={item.title || "AI 生成作品"} loading="lazy" />
      </Link>
      <div className="card-body">
        <div className="card-title-row">
          <Link href={`/gallery/${item.slug}`}><h2 className="card-title">{item.title || "未命名作品"}</h2></Link>
          <button className={`favorite-button ${item.viewerHasFavorited ? "active" : ""}`} type="button" disabled={!authenticated || saving} onClick={toggleFavorite} aria-label={authenticated ? (item.viewerHasFavorited ? "取消收藏" : "收藏作品") : "登录后收藏"}>收藏</button>
        </div>
        <div className="card-meta"><span>{item.workflowName}</span><span>{formatDate(item.publishedAt)}</span></div>
      </div>
    </article>
  );
}

export function GallerySkeleton() {
  return <div className="skeleton-grid" aria-label="正在加载作品">{Array.from({ length: 8 }).map((_, index) => <div className="skeleton-card" key={index} />)}</div>;
}

function ViewSelector({ value, onChange }: { value: ViewMode; onChange: (value: ViewMode) => void }) {
  return <div className="segmented" role="group" aria-label="选择画廊布局">{(Object.keys(viewLabels) as ViewMode[]).map((mode) => <button className={`segment-button ${value === mode ? "active" : ""}`} type="button" key={mode} aria-pressed={value === mode} onClick={() => onChange(mode)}>{viewLabels[mode]}</button>)}</div>;
}

function StateMessage({ mark, title, description, error = false }: { mark: string; title: string; description: string; error?: boolean }) {
  return <div className={`state-stage ${error ? "error-state" : ""}`}><div className="state-message"><div className="state-mark" aria-hidden="true">{mark}</div><h2>{title}</h2><p>{description}</p></div></div>;
}

function formatDate(value: string): string {
  try { return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric" }).format(new Date(value)); } catch { return ""; }
}
