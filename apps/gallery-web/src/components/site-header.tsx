"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import { publicAdminConsoleUrl } from "@/lib/admin-links";

interface SessionView {
  readonly role: "guest" | "user" | "admin";
  readonly userId?: number;
  readonly email?: string;
  readonly nickname?: string;
}

export function SiteHeader() {
  const [session, setSession] = useState<SessionView>();
  useEffect(() => {
    let active = true;
    fetch("/api/me/session", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return undefined;
        const body = await response.json() as SessionView;
        return body?.role === "guest" || body?.role === "user" || body?.role === "admin" ? body : undefined;
      })
      .then((value) => { if (active) setSession(value); })
      .catch(() => { if (active) setSession(undefined); });
    return () => { active = false; };
  }, []);

  const authenticated = session !== undefined && session.role !== "guest";
  const returnTo = typeof window === "undefined" ? "/gallery" : `${window.location.pathname}${window.location.search}`;
  return <header className="site-header"><div className="header-inner">
    <Link className="brand-lockup" href="/gallery" aria-label="Mavis Gallery 首页"><Image src="/brand/mavis-mark.svg" alt="Mavis" width={32} height={32} /><span>Mavis Gallery</span></Link>
    <nav className="nav-links" aria-label="主导航"><Link className="nav-link" href="/gallery">发现</Link><Link className="nav-link" href="/my-images">我的图片</Link><Link className="nav-link" href="/favorites">收藏</Link><Link className="nav-link" href="/pricing">会员</Link></nav>
    <div className="header-actions">
      {session === undefined ? null : authenticated
        ? <Link className="nav-link auth-link" href="/billing">{session.nickname || session.email || "我的账号"}</Link>
        : <Link className="button" href={`/login?next=${encodeURIComponent(returnTo)}`}>登录</Link>}
      {session?.role === "admin" && publicAdminConsoleUrl() !== undefined
        ? <Link className="nav-link auth-link" href={publicAdminConsoleUrl()!}>后台</Link>
        : null}
      <Link className="button" href="/billing">积分与账单</Link><Link className="button primary" href="/create">开始创作</Link>
    </div>
  </div></header>;
}
