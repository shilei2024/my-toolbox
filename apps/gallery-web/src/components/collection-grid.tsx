"use client";

import Link from "next/link";
import { useState } from "react";
import type { GalleryImageSummary } from "@/lib/gallery-types";
import { ArtworkCard } from "./gallery-explorer";

export function CollectionGrid({ initialItems, authenticated, emptyTitle, emptyCopy, removeWhenUnfavorited = false }: { initialItems: readonly GalleryImageSummary[]; authenticated: boolean; emptyTitle: string; emptyCopy: string; removeWhenUnfavorited?: boolean }) {
  const [items, setItems] = useState(initialItems);
  if (items.length === 0) return <section className="empty-collection"><div className="state-message"><div className="state-mark" aria-hidden="true">0</div><h2>{emptyTitle}</h2><p>{emptyCopy}</p><Link className="button primary" href="/gallery" style={{ marginTop: 18 }}>浏览公开作品</Link></div></section>;
  return <section className="gallery-panel"><div className="gallery-grid grid">{items.map((item) => <ArtworkCard key={item.id} item={item} authenticated={authenticated} onFavorite={(imageId, result) => setItems((current) => removeWhenUnfavorited && !result.active ? current.filter((entry) => entry.id !== imageId) : current.map((entry) => entry.id === imageId ? { ...entry, viewerHasFavorited: result.active, favoriteCount: result.count } : entry))} />)}</div></section>;
}
