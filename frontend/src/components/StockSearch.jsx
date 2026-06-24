import { useState } from "react";
import { getStock } from "../api";

export default function StockSearch({ onSelect }) {
  const [input, setInput] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSearch = async () => {
    if (!input.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await getStock(input.trim());
      setResult(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || "查詢失敗，請確認股票代號");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <h2>個股查詢</h2>
      <div className="search-bar">
        <input
          type="text"
          placeholder="輸入股票代號（例：2330）"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
        />
        <button onClick={handleSearch} disabled={loading}>
          {loading ? "查詢中..." : "查詢"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="stock-card">
          <div className="stock-header">
            <div>
              <h3>{result.name}</h3>
              <span className="ticker-badge">{result.ticker}</span>
            </div>
            <div className="price-block">
              <span className="price">{result.price} 元</span>
            </div>
          </div>

          <div className="info-grid">
            <InfoItem label="本益比" value={result.pe_ratio?.toFixed(2) ?? "—"} />
            <InfoItem label="股價淨值比" value={result.pb_ratio?.toFixed(2) ?? "—"} />
            <InfoItem label="殖利率" value={result.dividend_yield ? `${result.dividend_yield}%` : "—"} />
            <InfoItem label="產業" value={result.industry ?? "—"} />
            <InfoItem label="52週高" value={result.week_52_high ?? "—"} />
            <InfoItem label="52週低" value={result.week_52_low ?? "—"} />
          </div>

          <button className="detail-btn" onClick={() => onSelect(result.ticker)}>
            查看詳細分析
          </button>
        </div>
      )}
    </div>
  );
}

function InfoItem({ label, value }) {
  return (
    <div className="info-item">
      <span className="info-label">{label}</span>
      <span className="info-value">{value}</span>
    </div>
  );
}
