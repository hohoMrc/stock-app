import { useState, useEffect, useMemo } from "react";
import { getRevenueBoard, getRevenueIndustry } from "../api";

// 榜單定義：sortKey / dir 決定預設排序，另附過濾條件
const RANKS = [
  { id: "latest",   label: "最新公布",   sortKey: "rev",         dir: "desc" },
  { id: "yoy",      label: "年增榜",     sortKey: "yoy_pct",     dir: "desc" },
  { id: "mom",      label: "月增榜",     sortKey: "mom_pct",     dir: "desc" },
  { id: "cum_yoy",  label: "累計年增榜", sortKey: "cum_yoy_pct", dir: "desc" },
  { id: "scale",    label: "營收規模榜", sortKey: "rev",         dir: "desc" },
  { id: "high12",   label: "近12月新高", sortKey: "rev",         dir: "desc", only12mHigh: true },
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

// 千元 → 人類可讀（兆 / 億 / 萬）
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

// 台股慣例：漲/增用紅、跌/減用綠（對應 App 既有 --up / --down）
function pctClass(v) {
  if (v == null) return "";
  return v > 0 ? "up" : v < 0 ? "down" : "";
}

const MARKET_LABEL = { L: "上市", O: "上櫃" };

export default function RevenuePage({ watchlist = [], onSelect }) {
  const [board, setBoard] = useState({ ym: null, months: [], rows: [] });
  const [industryBoard, setIndustryBoard] = useState({ industries: [] });
  const [loading, setLoading] = useState(true);
  const [ym, setYm] = useState(null);

  const [rank, setRank] = useState("latest");
  const [market, setMarket] = useState("all");
  const [scale, setScale] = useState("all");
  const [industry, setIndustry] = useState("all");
  const [query, setQuery] = useState("");
  const [showIndustryBoard, setShowIndustryBoard] = useState(false);

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

  const industries = useMemo(() => {
    const set = new Set(board.rows.map((r) => r.industry).filter(Boolean));
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [board.rows]);

  const watchSet = useMemo(() => new Set(watchlist), [watchlist]);

  // ── KPI：依「市場」範圍（不受規模/產業/榜單/搜尋影響）統計整月概況 ──
  const kpi = useMemo(() => {
    const scope = board.rows.filter((r) => market === "all" || r.market === market);
    let sumRev = 0, sumRevLy = 0, sumCum = 0, sumCumLy = 0;
    let up = 0, down = 0, momUp = 0, counted = 0;
    for (const r of scope) {
      if (r.rev != null) sumRev += r.rev;
      if (r.rev_ly != null) sumRevLy += r.rev_ly;
      if (r.cum != null) sumCum += r.cum;
      if (r.cum_ly != null) sumCumLy += r.cum_ly;
      if (r.yoy_pct != null) {
        counted++;
        if (r.yoy_pct > 0) up++; else if (r.yoy_pct < 0) down++;
      }
      if (r.mom_pct != null && r.mom_pct > 0) momUp++;
    }
    return {
      total: scope.length,
      sumRev,
      yoyPct: sumRevLy ? (sumRev - sumRevLy) / sumRevLy * 100 : null,
      cumYoyPct: sumCumLy ? (sumCum - sumCumLy) / sumCumLy * 100 : null,
      up, down, momUp, counted,
      upRatio: counted ? Math.round(up / counted * 100) : 0,
    };
  }, [board.rows, market]);

  const rankDef = RANKS.find((r) => r.id === rank) || RANKS[0];

  // ── 清單：套用市場/規模/產業/搜尋/榜單過濾 + 排序 ──
  const rows = useMemo(() => {
    const scaleMin = SCALE_FILTERS.find((s) => s.id === scale)?.min ?? 0;
    const q = query.trim().toLowerCase();
    let list = board.rows.filter((r) => {
      if (market !== "all" && r.market !== market) return false;
      if ((r.rev ?? 0) < scaleMin) return false;
      if (industry !== "all" && r.industry !== industry) return false;
      if (rankDef.only12mHigh && r.is_12m_high !== true) return false;
      if (rankDef.onlyWatch && !watchSet.has(r.ticker)) return false;
      if (q && !(r.name?.toLowerCase().includes(q) || r.ticker?.toLowerCase().includes(q))) return false;
      return true;
    });
    const { sortKey, dir } = rankDef;
    list = [...list].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return dir === "asc" ? av - bv : bv - av;
    });
    return list;
  }, [board.rows, market, scale, industry, query, rankDef, watchSet]);

  // 年增率長條的刻度：用清單中 |yoy| 的 95 百分位當滿格，避免極端值壓扁其他
  const yoyScale = useMemo(() => {
    const vals = rows.map((r) => Math.abs(r.yoy_pct ?? 0)).filter((v) => v > 0).sort((a, b) => a - b);
    if (!vals.length) return 100;
    const p = vals[Math.floor(vals.length * 0.95)] || vals[vals.length - 1];
    return Math.max(p, 20);
  }, [rows]);

  const high12Accumulating =
    rank === "high12" && board.rows.length > 0 && board.rows.every((r) => r.is_12m_high == null);

  const ymLabel = ym ? `${ym.slice(0, 4)} 年 ${parseInt(ym.slice(5), 10)} 月` : "";

  return (
    <div className="page revenue-page">
      <div className="revenue-header">
        <h2>📈 {ymLabel} 營收</h2>
        {board.months.length > 0 && (
          <div className="revenue-month-pills">
            {board.months.slice(0, 6).map((m) => (
              <button key={m} className={m === ym ? "active" : ""} onClick={() => setYm(m)}>
                {parseInt(m.slice(5), 10)} 月
              </button>
            ))}
          </div>
        )}
      </div>
      <p className="revenue-note">
        資料取自證交所、櫃買中心公開的「上市／上櫃每月營業收入彙總表」，每天自動更新，僅供參考非投資建議。
      </p>

      {/* KPI 統計卡 */}
      <div className="rev-kpis">
        <div className="rev-kpi">
          <div className="rev-kpi-label">全體合計營收</div>
          <div className="rev-kpi-value">{fmtRev(kpi.sumRev)}</div>
        </div>
        <div className="rev-kpi">
          <div className="rev-kpi-label">合計年增率</div>
          <div className={`rev-kpi-value ${pctClass(kpi.yoyPct)}`}>{fmtPct(kpi.yoyPct)}</div>
        </div>
        <div className="rev-kpi">
          <div className="rev-kpi-label">年增家數</div>
          <div className="rev-kpi-value">
            {kpi.up} <span className="rev-kpi-sub">家 · {kpi.upRatio}%</span>
          </div>
        </div>
        <div className="rev-kpi">
          <div className="rev-kpi-label">累計年增率</div>
          <div className={`rev-kpi-value ${pctClass(kpi.cumYoyPct)}`}>{fmtPct(kpi.cumYoyPct)}</div>
        </div>
      </div>

      {/* 年增 / 年減 家數分布長條 */}
      {kpi.counted > 0 && (
        <div className="rev-dist">
          <div className="rev-dist-bar">
            <span className="seg up" style={{ flex: kpi.up || 0.001 }} />
            <span className="seg down" style={{ flex: kpi.down || 0.001 }} />
          </div>
          <div className="rev-dist-legend">
            <span className="up">年增 {kpi.up} 家</span>
            <span className="muted">月增 {kpi.momUp} 家</span>
            <span className="down">年減 {kpi.down} 家</span>
          </div>
        </div>
      )}

      {/* 產業成長榜（熱度長條，可收合） */}
      <button className="revenue-industry-toggle" onClick={() => setShowIndustryBoard((v) => !v)}>
        {showIndustryBoard ? "▾" : "▸"} 產業成長榜（同產業營收合計年增率）
      </button>
      {showIndustryBoard && industryBoard.industries.length > 0 && (() => {
        const maxAbs = Math.max(...industryBoard.industries.map((i) => Math.abs(i.yoy_pct ?? 0)), 1);
        return (
          <div className="rev-heat">
            {industryBoard.industries.slice(0, 20).map((i) => (
              <div key={i.industry} className="rev-heat-row">
                <span className="rev-heat-name" title={i.industry}>{i.industry}</span>
                <span className="rev-heat-track">
                  <span
                    className={`rev-heat-fill ${pctClass(i.yoy_pct)}`}
                    style={{ width: `${Math.min(Math.abs(i.yoy_pct ?? 0) / maxAbs * 100, 100)}%` }}
                  />
                </span>
                <span className={`rev-heat-val ${pctClass(i.yoy_pct)}`}>{fmtPct(i.yoy_pct)}</span>
              </div>
            ))}
          </div>
        );
      })()}

      {/* 榜單切換 */}
      <div className="revenue-ranks">
        {RANKS.map((r) => (
          <button key={r.id} className={rank === r.id ? "active" : ""} onClick={() => setRank(r.id)}>
            {r.label}
          </button>
        ))}
      </div>

      {/* 篩選 + 搜尋 */}
      <div className="revenue-filters">
        <div className="filter-group">
          {MARKETS.map((m) => (
            <button key={m.id} className={market === m.id ? "active" : ""} onClick={() => setMarket(m.id)}>
              {m.label}
            </button>
          ))}
        </div>
        <div className="revenue-filter-selects">
          <select value={scale} onChange={(e) => setScale(e.target.value)}>
            {SCALE_FILTERS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
            <option value="all">全部產業</option>
            {industries.map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
        </div>
        <input
          className="revenue-search"
          placeholder="搜尋股名或代號"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
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
          <div className="rev-cards">
            {rows.map((r, idx) => (
              <div key={r.ticker} className="rev-card" onClick={() => onSelect && onSelect(r.ticker)}>
                <div className="rev-rank">{idx + 1}</div>
                <div className="rev-card-body">
                  <div className="rev-card-main">
                    <div className="rev-card-title">
                      <b>{r.name}</b> <span className="rev-ticker">{r.ticker}</span>
                      {r.is_12m_high === true && <span className="rev-high-badge">新高</span>}
                    </div>
                    <div className="rev-card-sub">
                      {MARKET_LABEL[r.market] || ""}{r.industry ? ` · ${r.industry}` : ""}
                    </div>
                  </div>
                  <div className="rev-card-metrics">
                    <div className="rev-metric">
                      <div className="rev-metric-val">{fmtRev(r.rev)}</div>
                      <div className="rev-metric-lbl">當月營收</div>
                    </div>
                    <div className="rev-metric rev-metric-yoy">
                      <div className="rev-yoy-row">
                        <span className="rev-yoy-track">
                          <span
                            className={`rev-yoy-fill ${pctClass(r.yoy_pct)}`}
                            style={{ width: `${Math.min(Math.abs(r.yoy_pct ?? 0) / yoyScale * 100, 100)}%` }}
                          />
                        </span>
                        <span className={`rev-metric-val ${pctClass(r.yoy_pct)}`}>{fmtPct(r.yoy_pct)}</span>
                      </div>
                      <div className="rev-metric-lbl">年增率</div>
                    </div>
                    <div className="rev-metric">
                      <div className={`rev-metric-val ${pctClass(r.mom_pct)}`}>{fmtPct(r.mom_pct)}</div>
                      <div className="rev-metric-lbl">月增</div>
                    </div>
                    <div className="rev-metric">
                      <div className={`rev-metric-val ${pctClass(r.cum_yoy_pct)}`}>{fmtPct(r.cum_yoy_pct)}</div>
                      <div className="rev-metric-lbl">累計年增</div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
