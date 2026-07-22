import { useState, useEffect } from "react";
import { getIndustryStocks } from "../api";
import { MobileRankList } from "./TradeValueRanking";

const SORT_COLUMNS = [
  { key: "ticker",     label: "代號" },
  { key: "name",       label: "名稱" },
  { key: "price",      label: "成交價" },
  { key: "change_pct", label: "漲跌幅" },
  { key: "change",     label: "漲跌" },
];

export default function IndustryStocks({ industry, excludeTicker, useParent = false, onSelect, onBack }) {
  const [stocks, setStocks] = useState([]);
  const [resolvedIndustry, setResolvedIndustry] = useState(industry);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState(null);
  const [sortDir, setSortDir] = useState("desc");
  const [activeSub, setActiveSub] = useState(null); // null = 全部

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const res = await getIndustryStocks(industry, excludeTicker, useParent);
        setStocks(res.data.stocks);
        setResolvedIndustry(res.data.resolved_industry || industry);
        setActiveSub(null);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [industry, excludeTicker, useParent]);

  const expanded = resolvedIndustry !== industry;

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  // 大分類（如「半導體業」）股票數較多時，用個股自己的細分類（如果有標記）做子分類篩選，
  // 沒被標記細分類的股票（industry 直接等於大分類本身）歸在「其他」
  const subLabel = (s) => (s.industry && s.industry !== resolvedIndustry ? s.industry : "其他");
  const subCounts = {};
  for (const s of stocks) subCounts[subLabel(s)] = (subCounts[subLabel(s)] || 0) + 1;
  const subEntries = Object.entries(subCounts).sort((a, b) => b[1] - a[1]);
  const showSubFilter = subEntries.length > 1;

  const scopedStocks = activeSub ? stocks.filter((s) => subLabel(s) === activeSub) : stocks;

  const sortedStocks = sortKey
    ? [...scopedStocks].sort((a, b) => {
        const av = a[sortKey], bv = b[sortKey];
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        if (typeof av === "string") {
          return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
        }
        return sortDir === "asc" ? av - bv : bv - av;
      })
    : scopedStocks;

  return (
    <div className="page industry-stocks-page">
      <button className="back-btn" onClick={onBack}>← 返回</button>
      <h2>{industry} 相關個股</h2>
      {!loading && expanded && (
        <p className="industry-expanded-hint">
          「{industry}」歸類的股票較少，以下改顯示所屬的「{resolvedIndustry}」產業
        </p>
      )}

      {!loading && showSubFilter && (
        <div className="industry-sub-filters">
          <button className={activeSub === null ? "active" : ""} onClick={() => setActiveSub(null)}>
            全部 {stocks.length}
          </button>
          {subEntries.map(([label, count]) => (
            <button key={label} className={activeSub === label ? "active" : ""} onClick={() => setActiveSub(label)}>
              {label} {count}
            </button>
          ))}
        </div>
      )}

      {loading && <p className="loading-hint">查詢中...</p>}

      {!loading && stocks.length === 0 && (
        <p className="no-data">預設清單中未找到其他同產業個股</p>
      )}

      {!loading && stocks.length > 0 && (
        <div className="ranking-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                {SORT_COLUMNS.map(({ key, label }) => (
                  <th key={key} className="sortable" onClick={() => handleSort(key)}>
                    {label}{sortKey === key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedStocks.map((s) => {
                const up   = s.change > 0;
                const down = s.change < 0;
                const sign = up ? "+" : "";
                const dir  = up ? "up" : down ? "down" : "";
                return (
                  <tr
                    key={s.ticker}
                    className={`industry-row-clickable ${up ? "row-up" : down ? "row-down" : ""}`}
                    onClick={() => onSelect(s.ticker)}
                  >
                    <td>{s.ticker}</td>
                    <td>{s.name}</td>
                    <td>{s.price ?? "—"}</td>
                    <td className={dir}>{s.change_pct != null ? `${sign}${s.change_pct}%` : "—"}</td>
                    <td className={dir}>{s.change != null ? `${sign}${s.change}` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <MobileRankList
            stocks={sortedStocks.map((s) => ({
              ticker: s.ticker,
              name: s.name,
              close: s.price,
              change: s.change,
              change_pct: s.change_pct,
              exchange: s.exchange === "TW" ? "上市" : s.exchange === "TWO" ? "上櫃" : s.exchange,
            }))}
            onSelect={onSelect}
          />
        </div>
      )}
    </div>
  );
}
