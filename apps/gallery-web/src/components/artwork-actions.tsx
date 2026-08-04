"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function ArtworkActions({ imageId, initialLiked, initialFavorited, initialLikeCount, initialFavoriteCount, authenticated, canDelete }: { imageId: string; initialLiked: boolean; initialFavorited: boolean; initialLikeCount: number; initialFavoriteCount: number; authenticated: boolean; canDelete: boolean }) {
  const router = useRouter();
  const [liked, setLiked] = useState(initialLiked);
  const [favorited, setFavorited] = useState(initialFavorited);
  const [likeCount, setLikeCount] = useState(initialLikeCount);
  const [favoriteCount, setFavoriteCount] = useState(initialFavoriteCount);
  const [busy, setBusy] = useState<string>();
  const [message, setMessage] = useState<string>();

  async function interaction(kind: "like" | "favorite", active: boolean) {
    if (!authenticated) { setMessage("请先登录后再操作。"); return; }
    setBusy(kind); setMessage(undefined);
    try {
      const response = await fetch(`/api/images/${imageId}/${kind}`, { method: active ? "PUT" : "DELETE" });
      const result = await response.json() as { active?: boolean; count?: number; error?: { message?: string } };
      if (!response.ok || typeof result.active !== "boolean" || typeof result.count !== "number") throw new Error(result.error?.message || "操作失败");
      if (kind === "like") { setLiked(result.active); setLikeCount(result.count); }
      else { setFavorited(result.active); setFavoriteCount(result.count); }
    } catch (error) { setMessage(error instanceof Error ? error.message : "操作失败"); }
    finally { setBusy(undefined); }
  }

  async function download() {
    setBusy("download"); setMessage(undefined);
    try {
      const response = await fetch(`/api/images/${imageId}/download`, { method: "POST" });
      const result = await response.json() as { url?: string; error?: { message?: string } };
      if (!response.ok || !result.url) throw new Error(result.error?.message || "下载暂不可用");
      window.location.assign(result.url);
    } catch (error) { setMessage(error instanceof Error ? error.message : "下载暂不可用"); }
    finally { setBusy(undefined); }
  }

  async function remove() {
    if (!canDelete || !window.confirm("确定删除这张图片？图片会立即从 Gallery 下架。")) return;
    setBusy("delete"); setMessage(undefined);
    try {
      const response = await fetch(`/api/images/${imageId}`, { method: "DELETE" });
      if (!response.ok) { const result = await response.json() as { error?: { message?: string } }; throw new Error(result.error?.message || "删除失败"); }
      router.replace("/my-images"); router.refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "删除失败"); setBusy(undefined); }
  }

  return <div className="artwork-action-stack"><div className="detail-actions"><button className={`button ${liked ? "primary" : ""}`} type="button" disabled={busy === "like"} onClick={() => void interaction("like", !liked)}>喜欢 · {likeCount}</button><button className={`button ${favorited ? "primary" : ""}`} type="button" disabled={busy === "favorite"} onClick={() => void interaction("favorite", !favorited)}>收藏 · {favoriteCount}</button><button className="button" type="button" disabled={busy === "download"} onClick={() => void download()}>下载</button>{canDelete && <button className="button danger" type="button" disabled={busy === "delete"} onClick={() => void remove()}>删除</button>}</div>{message && <p className="inline-message" role="status">{message}</p>}</div>;
}
