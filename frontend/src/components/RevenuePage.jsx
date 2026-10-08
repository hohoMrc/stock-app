import { useState, useEffect, useMemo } from "react";
import { getRevenueBoard, getRevenueIndustry } from "../api";

// 榜單定義：key 用來預設排序，dir 預設方向，filter 為可選的額外篩選條件
const RANKS = [
  { id: "latest",   label: "最新公布",   sortKey: "rev",         dir: "desc" },
  { id: "yoy",      label: "年增榜",     sortKey: "yoy_pct",     dir: "desc" },
  { id: "mom",      label: "月增榜",     sortKey: "mom_pct",     dir: "desc" },
  { id: "cum_yoy",  label: "累計年增榜", sortKey: "cum_yoy_pct", dir: "desc" },
  { id: "scale",    label: "營收規模榜", sortKey: "rev",         dir: "desc" },
  { id: "high12",   label: "近12月新高", sortKey: "yoy_pct",     dir: "desc", only12mHigh: true },
  { id: "yoy_drop", label: "年減最多",   sortKey: "yoy_pct",     dir: "asc" },
  { id: "mine",     label: "我的自選",   sortKey: "yoy_pct",     dir: "desc", onlyWatch: true },
];

// 月營收規模門檻（單位：千元；1 億 = 100,000 千元）
const SCALE_FILTERS = [
  { id: "all", label: "不限規模", min: 0 },
  { id: "1e",  label: "1 億以上",   min: 100000 },
  { id: "10e", label: "10 億以上",  min: 1000000 },
  { id: "100e",label: "100 億以上", min: 10000000 },
];

const MARKETS = [
  { id: "all", label: "上市＋上櫃" },
  { id: "L",   label: "只看上市" },
  { id: "O",   label: "只看上櫃" },
];

// 千元 → 人類可讀（億 / 兆）
function fmtRev(thousand) {
  if (thousand == null) return "—";
  const yi = thousand / 100000; // 千元 → 億
  if (yi >= 10000) return (yi / 10000).toFixed(2) + " 兆";
  if (yi >= 1) return yi.toFixed(yi >= 100 ? 0 : 1) + " 億";
  return (thousand / 1000).toFixed(0) + " 萬";
}

function fmtPct(v) {
  if (v == null) return "—";
  return (v > 0 ? "+" : "") + v.toFixed(1) + "%";
}

function pctClass(v) {
  if (v == null) return "";
  return v > 0 ? "up" : v < 0 ? "down" : "";
}

const COLUMNS = [
  { key: "name",        label: "股票" },
  { key: "industry",    label: "產業" },
  { key: "rev",         label: "當月營收" },
  { key: "yoy_pct",     label: "年增" },
  { key: "mom_pct",     label: "月增" },
  { key: "cum",         label: "累計營收" },
  { key: "cum_yoy_pct", label: "累計年增" },
];

export default function RevenuePage({ watchlist = [], onSelect }) {
  const [board, setBoard] = useState({ ym: null, months: [], rows: [] });
  const [industryBoard, setIndustryBoard] = useState({ industries: [] });
  const [loading, setLoading] = useState(true);
  const [ym, setYm] = useState(null);

  const [rank, setRank] = useState("latest");
  const [market, setMarket] = useState("all");
  const [scale, setScale] = useState("all");
  const [industry, setIndustry] = useState("all");
  const [showIndustryBoard, setShowIndustryBoard] = useState(false);

  // 手動排序：點表頭後覆蓋榜單預設排序
  const [sortKey, setSortKey] = useState(null);
  const [sortDir, setSortDir] = useState("desc");

  useEffect(() => {
    setLoading(true);
    getRevenueBoard(ym)
      .then((res) => {
        setBoard(res.data);
        if (!ym && res.data.ym) setYm(res.data.ym);
      })
      .finally(() => setLoading(false));
  }, [ym]);

  useEffect(() => {
    const mkt = market === "all" ? undefined : market;
    getRevenueIndustry(ym, mkt).then((res) => setIndustryBoard(res.data));
  }, [ym, market]);

  // 切換榜單時清除手動排序，回到榜單預設
  const changeRank = (id) => {
    setRank(id);
    setSortKey(null);
  };

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const industries = useMemo(() => {
    const set = new Set(board.rows.map((r) => r.industry).filter(Boolean));
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [board.rows]);

  const rankDef = RANKS.find((r) => r.id === rank) || RANKS[0];
  const watchSet = useMemo(() => new Set(watchlist), [watchlist]);

  const rows = useMemo(() => {
    const scaleMin = SCALE_FILTERS.find((s) => s.id === scale)?.min ?? 0;
    let list = board.rows.filter((r) => {
      if (market !== "all" && r.market !== market) return false;
      if ((r.rev ?? 0) < scaleMin) return false;
      if (industry !== "all" && r.industry !== industry) return false;
      if (rankDef.only12mHigh && r.is_12m_high !== true) return false;
      if (rankDef.onlyWatch && !watchSet.has(r.ticker)) return false;
      return true;
    });

    const key = sortKey || rankDef.sortKey;
    const dir = sortKey ? sortDir : rankDef.dir;
    list = [...list].sort((a, b) => {
      const av = a[key], bv = b[key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "string") {
        return dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return dir === "asc" ? av - bv : bv - av;
    });
    return list;
  }, [board.rows, market, scale, industry, rank, sortKey, sortDir, rankDef, watchSet]);

  const high12Accumulating =
    rank === "high12" && board.rows.length > 0 && board.rows.every((r) => r.is_12m_high == null);

  return (
    <div className="page revenue-page">
      <div className="revenue-header">
        <h2>📈 月營收佈告欄</h2>
        {board.months.length > 0 && (
          <select value={ym || ""} onChange={(e) => setYm(e.target.value)} className="revenue-month-select">
            {board.months.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        )}
      </div>
      <p className="revenue-note">
        資料取自證交所、櫃買中心公開的「上市／上櫃每月營業收入彙總表」，每天自動更新，僅供參考非投資建議。
      </p>

      {/* 產業成長榜（可收合） */}
      <button className="revenue-industry-toggle" onClick={() => setShowIndustryBoard((v) => !v)}>
        {showIndustryBoard ? "▾" : "▸"} 產業成長榜（同產業營收合計年增率）
      </button>
      {showIndustryBoard && (
        <div className="revenue-industry-board">
          {industryBoard.industries.slice(0, 15).map((i) => (
            <div key={i.industry} className="revenue-industry-row">
              <span className="ind-name">{i.industry}</span>
              <span className="ind-rev">{fmtRev(i.rev)}</span>
              <span className={`ind-yoy ${pctClass(i.yoy_pct)}`}>{fmtPct(i.yoy_pct)}</span>
            </div>
          ))}
        </div>
      )}

      {/* 榜單切換 */}
      <div className="revenue-ranks">
        {RANKS.map((r) => (
          <button key={r.id} className={rank === r.id ? "active" : ""} onClick={() => changeRank(r.id)}>
            {r.label}
          </button>
        ))}
      </div>

      {/* 篩選 */}
      <div className="revenue-filters">
        <div className="filter-group">
          {MARKETS.map((m) => (
            <button key={m.id} className={market === m.id ? "active" : ""} onClick={() => setMarket(m.id)}>
              {m.label}
            </button>
          ))}
        </div>
        <div className="filter-group">
          {SCALE_FILTERS.map((s) => (
            <button key={s.id} className={scale === s.id ? "active" : ""} onClick={() => setScale(s.id)}>
              {s.label}
            </button>
          ))}
        </div>
        <select value={industry} onChange={(e) => setIndustry(e.target.value)} className="revenue-industry-select">
          <option value="all">全部產業</option>
          {industries.map((i) => (
            <option key={i} value={i}>{i}</option>
          ))}
        </select>
      </div>

      {loading && <p className="loading-hint">營收資料載入中…</p>}

      {!loading && high12Accumulating && (
        <p className="no-data">近 12 月新高需要累積 12 個月的歷史資料，目前資料累積中，請之後再看。</p>
      )}

      {!loading && !high12Accumulating && rows.length === 0 && (
        <p className="no-data">沒有符合條件的個股。</p>
      )}

      {!loading && rows.length > 0 && (
        <>
          <p className="revenue-count">共 {rows.length} 檔</p>
          <div className="ranking-table-wrap">
            <table className="result-table">
              <thead>
                <tr>
                  {COLUMNS.map(({ key, label }) => (
                    <th key={key} className="sortable" onClick={() => handleSort(key)}>
                      {label}{(sortKey || rankDef.sortKey) === key ? ((sortKey ? sortDir : rankDef.dir) === "asc" ? " ▲" : " ▼") : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.ticker} className="clickable" onClick={() => onSelect && onSelect(r.ticker)}>
                    <td>
                      <span className="rev-ticker">{r.ticker}</span> {r.name}
                      {r.is_12m_high === true && <span className="rev-high-badge">新高</span>}
                    </td>
                    <td className="rev-industry">{r.industry || "—"}</td>
                    <td>{fmtRev(r.rev)}</td>
                    <td className={pctClass(r.yoy_pct)}>{fmtPct(r.yoy_pct)}</td>
                    <td className={pctClass(r.mom_pct)}>{fmtPct(r.mom_pct)}</td>
                    <td>{fmtRev(r.cum)}</td>
                    <td className={pctClass(r.cum_yoy_pct)}>{fmtPct(r.cum_yoy_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
