export default function Loading() {
  return (
    <main className="page-shell">
      <div className="skeleton-grid" aria-label="页面加载中">
        {Array.from({ length: 8 }).map((_, index) => <div className="skeleton-card" key={index} />)}
      </div>
    </main>
  );
}
