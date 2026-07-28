export const PAGE_SIZE = 10;

export default function Pagination({ page, totalPages, onChange }) {
  if (totalPages <= 1) return null;
  return (
    <div className="pagination">
      <button className="refresh-btn" onClick={() => onChange(page - 1)} disabled={page <= 1}>
        ‹ 上一頁
      </button>
      <span className="pagination-info">第 {page} / {totalPages} 頁</span>
      <button className="refresh-btn" onClick={() => onChange(page + 1)} disabled={page >= totalPages}>
        下一頁 ›
      </button>
    </div>
  );
}
