"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="page-shell">
      <section className="state-stage error-state">
        <div className="state-message">
          <div className="state-mark" aria-hidden="true">!</div>
          <h2>页面暂时无法显示</h2>
          <p>请稍后重试。错误详情不会直接暴露给浏览器。</p>
          <button className="button" type="button" onClick={reset} style={{ marginTop: 18 }}>重试</button>
        </div>
      </section>
    </main>
  );
}
