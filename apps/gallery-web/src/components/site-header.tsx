"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { publicAdminConsoleUrl } from "@/lib/admin-links";

interface SessionView {
  readonly role: "guest" | "user" | "admin";
  readonly userId?: number;
  readonly email?: string;
  readonly nickname?: string;
}

interface SiteHeaderProps {
  readonly mainSiteUrl?: string;
}

const navigation = [
  { href: "/gallery", label: "发现" },
  { href: "/my-images", label: "我的图片" },
  { href: "/tasks", label: "任务中心" },
  { href: "/favorites", label: "收藏" },
  { href: "/pricing", label: "会员" },
] as const;

export function SiteHeader({ mainSiteUrl }: SiteHeaderProps) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
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
  const returnTo = pathname || "/gallery";
  const adminUrl = session?.role === "admin" ? publicAdminConsoleUrl() : undefined;
  const closeMenu = () => setMenuOpen(false);

  return (
    <header className="site-header">
      <div className="header-inner">
        <Link className="brand-lockup" href="/gallery" aria-label="Mavis Gallery 首页" onClick={closeMenu}>
          <Image src="/brand/mavis-mark.svg" alt="" width={34} height={34} loading="eager" />
          <span><strong>Mavis</strong><small>Gallery</small></span>
        </Link>

        <nav className="nav-links" aria-label="Gallery 主导航">
          {mainSiteUrl ? <a className="nav-link nav-link-main" href={mainSiteUrl}>工具箱</a> : null}
          {navigation.map((item) => <Link key={item.href} className={`nav-link${isActive(pathname, item.href) ? " active" : ""}`} href={item.href}>{item.label}</Link>)}
        </nav>

        <div className="header-actions">
          {session === undefined ? null : authenticated
            ? <Link className="nav-link auth-link" href="/billing">{session.nickname || session.email || "我的账号"}</Link>
            : <Link className="button" href={`/login?next=${encodeURIComponent(returnTo)}`}>登录</Link>}
          {adminUrl ? <a className="nav-link auth-link" href={adminUrl}>后台</a> : null}
          <Link className="button" href="/billing">积分与账单</Link>
          <Link className="button primary" href="/create">开始创作</Link>
        </div>

        <button
          className={`mobile-menu-toggle${menuOpen ? " open" : ""}`}
          type="button"
          aria-label={menuOpen ? "关闭导航菜单" : "打开导航菜单"}
          aria-controls="gallery-mobile-menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span /><span />
        </button>
      </div>

      <nav id="gallery-mobile-menu" className={`mobile-nav-panel${menuOpen ? " open" : ""}`} aria-label="Gallery 移动导航" hidden={!menuOpen}>
        <div className="mobile-nav-primary">
          {mainSiteUrl ? <a className="mobile-nav-main" href={mainSiteUrl} onClick={closeMenu}><span>返回主站工具箱</span><i>↗</i></a> : null}
          {navigation.map((item) => <Link key={item.href} className={isActive(pathname, item.href) ? "active" : ""} href={item.href} onClick={closeMenu}><span>{item.label}</span><i>→</i></Link>)}
        </div>
        <div className="mobile-nav-actions">
          {session === undefined ? null : authenticated
            ? <Link className="button" href="/billing" onClick={closeMenu}>{session.nickname || session.email || "我的账号"}</Link>
            : <Link className="button" href={`/login?next=${encodeURIComponent(returnTo)}`} onClick={closeMenu}>登录</Link>}
          {adminUrl ? <a className="button" href={adminUrl}>后台</a> : null}
          <Link className="button" href="/billing" onClick={closeMenu}>积分与账单</Link>
          <Link className="button primary" href="/create" onClick={closeMenu}>开始创作</Link>
        </div>
      </nav>
    </header>
  );
}

function isActive(pathname: string, href: string): boolean {
  return href === "/gallery" ? pathname === href || pathname.startsWith("/gallery/") : pathname === href || pathname.startsWith(`${href}/`);
}
