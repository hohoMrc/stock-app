import { useState, useEffect } from "react";
import { getTradeValueRanking } from "../api";

export default function TradeValueRanking({ onSelect }) {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getTradeValueRanking(50);
      setStocks(res.data.stocks);
      setUpdatedAt(new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" }));
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "載入失敗");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="page">
      <div className="ranking-header">
        <h2>成交值排行</h2>
        <div className="ranking-meta">
          {updatedAt && <span className="ranking-time">更新：{updatedAt}</span>}
          <button className="refresh-btn" onClick={load} disabled={loading}>
            {loading ? "載入中..." : "↻ 重新整理"}
          </button>
        </div>
      </div>
      <p className="ranking-hint">盤中即時排行（Fugle）；非交易時段自動退回 TWSE／TPEx 收盤資料。快取 5 分鐘。</p>

      {error && <p className="error">❌ {error}</p>}

      {!loading && !error && stocks.length === 0 && (
        <p className="no-data">暫無資料（可能尚未收盤）</p>
      )}

      {stocks.length > 0 && (
        <div className="ranking-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                <th>#</th>
                <th>代號</th>
                <th>名稱</th>
                <th>收盤</th>
                <th>漲跌</th>
                <th>漲跌幅</th>
                <th>成交值(億)</th>
                <th>市場</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((s, i) => {
                const up   = s.change > 0;
                const down = s.change < 0;
                const cls  = up ? "deviation-up" : down ? "deviation-down" : "";
                const sign = up ? "+" : "";
                return (
                  <tr key={s.ticker}>
                    <td className="rank-num">{i + 1}</td>
                    <td>{s.ticker}</td>
                    <td>{s.name}</td>
                    <td>{s.close ?? "—"}</td>
                    <td className={cls}>{s.change != null ? `${sign}${s.change}` : "—"}</td>
                    <td className={cls}>{s.change_pct != null ? `${sign}${s.change_pct}%` : "—"}</td>
                    <td className="trade-value-cell">{s.trade_value_yi ?? "—"}</td>
                    <td className="exchange-badge-cell">
                      <span className={`exchange-badge ${s.exchange === "上市" ? "listed" : "otc"}`}>
                        {s.exchange}
                      </span>
                    </td>
                    <td>
                      <button className="view-btn" onClick={() => onSelect(s.ticker)}>查看</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
