import { useState } from "react";
import { getWarrantLookup } from "../api";
import WarrantTable from "./WarrantTable";
import { InfoItem } from "./StockDetail";

export default function WarrantLookup({ onSelect }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const runSearch = async (q) => {
    if (!q) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await getWarrantLookup(q);
      setResult(res.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "查詢失敗");
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = () => runSearch(input.trim());

  const handleViewUnderlyingWarrants = (underlyingTicker) => {
    setInput(underlyingTicker);
    runSearch(underlyingTicker);
  };

  return (
    <div className="page">
      <h2>權證查詢</h2>
      <p className="ranking-hint">輸入股票代號查它的相關權證，或直接輸入權證代號查該檔詳細資料</p>
      <div className="search-bar">
        <input
          type="text"
          placeholder="例：2330（股票）或 030573（權證）"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          autoComplete="off"
        />
        <button onClick={handleSearch} disabled={loading}>
          {loading ? "查詢中..." : "查詢"}
        </button>
      </div>

      {error && <p className="error">❌ {error}</p>}

      {result?.mode === "not_found" && (
        <p className="no-data">查無此股票或權證代號</p>
      )}

      {result?.mode === "stock" && (
        <div className="warrant-section" style={{ marginTop: 20 }}>
          <h3>{result.underlying_ticker} 相關權證</h3>
          <WarrantTable
            key={result.underlying_ticker}
            warrants={result.warrants}
            histVolPct={result.hist_vol_pct}
            loading={false}
          />
        </div>
      )}

      {result?.mode === "warrant" && (
        <WarrantDetailCard
          warrant={result.warrant}
          onSelectStock={onSelect}
          onViewUnderlyingWarrants={handleViewUnderlyingWarrants}
        />
      )}
    </div>
  );
}

function WarrantDetailCard({ warrant: w, onSelectStock, onViewUnderlyingWarrants }) {
  return (
    <div className="warrant-section" style={{ marginTop: 20 }}>
      <h3>{w.ticker} {w.name}</h3>
      <p className="ranking-hint">標的：{w.underlying_name}（{w.underlying_ticker}）</p>
      <div className="info-grid">
        <InfoItem label="現價" value={w.price ?? "—"} />
        <InfoItem
          label="漲跌幅"
          value={w.change_pct != null ? `${w.change_pct > 0 ? "+" : ""}${w.change_pct}%` : "—"}
        />
        <InfoItem label="成交量(張)" value={w.volume_zhang != null ? w.volume_zhang.toLocaleString() : "—"} />
        <InfoItem label="在外流通(張)" value={w.outstanding_volume != null ? w.outstanding_volume.toLocaleString() : "—"} />
        <InfoItem label="履約價" value={w.exercise_price ?? "—"} />
        <InfoItem label="到期日" value={`${w.maturity_date}（剩${w.days_left}天）`} />
        <InfoItem
          label="價內外"
          value={w.moneyness_pct != null ? `${w.moneyness_pct > 0 ? "+" : ""}${w.moneyness_pct}%` : "—"}
        />
        <InfoItem label="槓桿" value={w.leverage != null ? `${w.leverage}x` : "—"} />
        <InfoItem label="隱含波動率" value={w.iv_pct != null ? `${w.iv_pct}%` : "—"} />
      </div>
      <div className="warrant-detail-actions">
        <button className="view-btn" onClick={() => onSelectStock(w.underlying_ticker)}>
          查看標的個股頁
        </button>
        <button className="view-btn" onClick={() => onViewUnderlyingWarrants(w.underlying_ticker)}>
          查看標的所有相關權證
        </button>
      </div>
    </div>
  );
}
