import Link from "next/link";

export default function NotFound() {
  return <main className="page-shell"><section className="state-stage"><div className="state-message"><div className="state-mark" aria-hidden="true">404</div><h1>没有找到这件作品</h1><p>作品可能尚未公开、未通过审核，或已经被作者删除。</p><Link className="button primary" href="/gallery" style={{ marginTop: 18 }}>浏览公开作品</Link></div></section></main>;
}
