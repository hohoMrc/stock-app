import { useState, useEffect } from "react";
import { getUpcomingDividends } from "../api";

const TYPE_LABEL = { "息": "除息", "權": "除權", "權息": "除權息" };

function formatDate(d) {
  const [, m, day] = d.split("-");
  return `${parseInt(m)}/${parseInt(day)}`;
}

export default function DividendCalendar({ onSelect }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);

  const load = (force = false) => {
    setLoading(true);
    setError(null);
    getUpcomingDividends(60, force)
      .then((res) => {
        setRows(res.data.dividends || []);
        setUpdatedAt(new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" }));
      })
      .catch((e) => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="page">
      <div className="ranking-header">
        <h2>除權息行事曆</h2>
        <div className="ranking-meta">
          {updatedAt && <span className="ranking-time">更新：{updatedAt}</span>}
          <button className="refresh-btn" onClick={() => load(true)} disabled={loading}>
            {loading ? "載入中..." : "↻ 重新整理"}
          </button>
        </div>
      </div>

      <p className="ranking-hint">近 60 天全市場即將除權息股票，依日期由近到遠排序。快取 5 分鐘。</p>

      {error && <p className="error">❌ {error}</p>}
      {!loading && !error && rows.length === 0 && (
        <p className="no-data">近期無除權息資料</p>
      )}

      {rows.length > 0 && (
        <div className="ranking-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                <th>日期</th><th>代號</th><th>名稱</th><th>類型</th>
                <th>現金股利</th><th>股票股利(股)</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.ticker}-${r.date}-${i}`}>
                  <td>{formatDate(r.date)}</td>
                  <td className="col-ticker">{r.ticker}</td>
                  <td className="col-name">{r.name}</td>
                  <td>{TYPE_LABEL[r.dividend_type] ?? r.dividend_type ?? "—"}</td>
                  <td>{r.cash_dividend != null ? r.cash_dividend : "—"}</td>
                  <td>{r.stock_dividend_shares != null ? r.stock_dividend_shares : "—"}</td>
                  <td><button className="view-btn" onClick={() => onSelect(r.ticker)}>查看</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
