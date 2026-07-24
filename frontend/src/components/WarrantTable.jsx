import { useState } from "react";

// 某標的股的權證清單：標的歷史波動率提示 + 近價/高槓桿/相對便宜篩選 + 可點擊排序的表格。
// 被 StockDetail.jsx（個股頁「權證」分頁）跟 WarrantLookup.jsx（權證查詢頁）共用，
// 內部自己管理篩選/排序狀態，呼叫端傳 key={ticker} 讓切換標的時自然重新掛載、重置狀態。
export default function WarrantTable({ warrants, histVolPct, loading }) {
  const [nearMoney, setNearMoney] = useState(false);
  const [highLeverage, setHighLeverage] = useState(false);
  const [cheap, setCheap] = useState(false);
  const [sortKey, setSortKey] = useState(null);
  const [sortDir, setSortDir] = useState("desc");

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  if (loading) return <p className="loading-hint">查詢中...</p>;
  if (!warrants || warrants.length === 0) return <p className="no-data">目前無相關權證</p>;

  const filtered = warrants.filter((w) =>
    (!nearMoney || (w.moneyness_pct != null && Math.abs(w.moneyness_pct) <= 10)) &&
    (!highLeverage || (w.leverage != null && w.leverage >= 5)) &&
    (!cheap || w.is_cheap === true)
  );

  const sorted = sortKey
    ? [...filtered].sort((a, b) => {
        const av = a[sortKey], bv = b[sortKey];
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        if (typeof av === "string") {
          return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
        }
        return sortDir === "asc" ? av - bv : bv - av;
      })
    : filtered;

  const columns = [
    { key: "ticker", label: "代號" },
    { key: "name", label: "名稱" },
    { key: "price", label: "現價" },
    { key: "change_pct", label: "漲跌幅" },
    { key: "volume_zhang", label: "成交量(張)" },
    { key: "outstanding_volume", label: "在外流通(張)" },
    { key: "exercise_price", label: "履約價" },
    { key: "days_left", label: "剩餘天數" },
    { key: "moneyness_pct", label: "價內外" },
    { key: "leverage", label: "槓桿" },
    { key: "iv_pct", label: "隱含波動率" },
  ];

  return (
    <>
      {histVolPct != null && (
        <p className="warrant-hist-vol-hint">標的近20日歷史波動率：{histVolPct}%（供對照隱含波動率是否偏貴/偏便宜）</p>
      )}
      <div className="warrant-filters">
        <label className="check-label">
          <input type="checkbox" checked={nearMoney} onChange={(e) => setNearMoney(e.target.checked)} />
          近價（價內外 ±10% 內）
        </label>
        <label className="check-label">
          <input type="checkbox" checked={highLeverage} onChange={(e) => setHighLeverage(e.target.checked)} />
          高槓桿（≥5倍）
        </label>
        <label className="check-label">
          <input type="checkbox" checked={cheap} onChange={(e) => setCheap(e.target.checked)} />
          相對便宜（IV低於歷史波動率）
        </label>
      </div>
      {filtered.length === 0 ? (
        <p className="no-data">沒有符合篩選條件的權證</p>
      ) : (
        <table className="result-table warrant-table">
          <thead>
            <tr>
              {columns.map(({ key, label }) => (
                <th key={key} className="sortable" onClick={() => handleSort(key)}>
                  {label}{sortKey === key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((w) => (
              <tr key={w.ticker} className={w.change_pct > 0 ? "row-up" : w.change_pct < 0 ? "row-down" : ""}>
                <td className="col-ticker">{w.ticker}</td>
                <td className="col-name">{w.name}</td>
                <td>{w.price ?? "—"}</td>
                <td className={w.change_pct > 0 ? "deviation-up" : w.change_pct < 0 ? "deviation-down" : ""}>
                  {w.change_pct != null ? `${w.change_pct > 0 ? "+" : ""}${w.change_pct}%` : "—"}
                </td>
                <td>{w.volume_zhang != null ? w.volume_zhang.toLocaleString() : "—"}</td>
                <td>{w.outstanding_volume != null ? w.outstanding_volume.toLocaleString() : "—"}</td>
                <td>{w.exercise_price ?? "—"}</td>
                <td>{w.days_left}</td>
                <td className={w.moneyness_pct > 0 ? "deviation-up" : w.moneyness_pct < 0 ? "deviation-down" : ""}>
                  {w.moneyness_pct != null ? `${w.moneyness_pct > 0 ? "+" : ""}${w.moneyness_pct}%` : "—"}
                </td>
                <td>{w.leverage != null ? `${w.leverage}x` : "—"}</td>
                <td className={w.is_cheap ? "deviation-up" : ""}>
                  {w.iv_pct != null ? `${w.iv_pct}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
