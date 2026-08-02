import Image from "next/image";
import Link from "next/link";

export function SiteHeader() {
  return <header className="site-header"><div className="header-inner">
    <Link className="brand-lockup" href="/gallery" aria-label="Mavis Gallery 首页"><Image src="/brand/mavis-mark.svg" alt="Mavis" width={32} height={32} /><span>Mavis Gallery</span></Link>
    <nav className="nav-links" aria-label="主要导航"><Link className="nav-link" href="/gallery">发现</Link><Link className="nav-link" href="/my-images">我的图片</Link><Link className="nav-link" href="/favorites">收藏</Link><Link className="nav-link" href="/pricing">会员</Link></nav>
    <div className="header-actions"><Link className="button" href="/billing">积分与账单</Link><button className="button primary" type="button" disabled title="将在生成 API 接入后启用">开始创作</button></div>
  </div></header>;
}
