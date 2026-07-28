export default function PaperPageActions({ onRefresh, onDeposit, loading, depositing, depositLabel }) {
  return (
    <div className="paper-page-actions">
      <button className="refresh-btn" onClick={onRefresh} disabled={loading}>
        {loading ? "更新中..." : "↻ 重新整理"}
      </button>
      <button className="deposit-btn" onClick={onDeposit} disabled={depositing}>
        {depositing ? "入金中..." : depositLabel}
      </button>
    </div>
  );
}
