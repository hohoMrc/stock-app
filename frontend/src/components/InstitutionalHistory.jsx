import { useState, useEffect } from "react";
import { ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from "recharts";
import { getMarketInstitutionalHistory } from "../api";

const WHO = [
  { key: "foreign", label: "外資",   color: "#38bdf8" },
  { key: "trust",   label: "投信",   color: "#f59e0b" },
  { key: "dealer",  label: "自營商", color: "#a78bfa" },
];
const CUM_COLOR = "#f472b6";
const MARKETS = [
  { key: "",      label: "合計" },
  { key: "_twse", label: "上市" },
  { key: "_tpex", label: "上櫃" },
];

const upDown = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
const fmt = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
const round2 = (v) => Math.round(v * 100) / 100;

// 大盤狀態：全市場三大法人買賣超歷史（億元）彈窗，可切天數與上市/上櫃；點背景、✕ 或按 Esc 關閉
export default function InstitutionalHistory({ onClose }) {
  const [days, setDays] = useState(20);
  const [market, setMarket] = useState("");
  const [records, setRecords] = useState(null); // null = 載入中
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setRecords(null);
    setError("");
    getMarketInstitutionalHistory(days)
      .then((res) => { if (alive) setRecords(res.data.records || []); })
      .catch(() => { if (alive) { setRecords([]); setError("讀取失敗，請稍後再試"); } });
    return () => { alive = false; };
  }, [days]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    // 彈窗開著時鎖住背景捲動，捲表格不會連帶捲到後面的頁面
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  const val = (r, who) => r[`${who}_net_yi${market}`];
  const rows = (records || []).map((r) => {
    const v = Object.fromEntries(WHO.map(({ key }) => [key, val(r, key)]));
    const total = WHO.every(({ key }) => v[key] != null) ? round2(WHO.reduce((s, { key }) => s + v[key], 0)) : null;
    return { date: r.date, ...v, total };
  });
  // 圖表由舊到新，日期只留月/日；cum 是區間起點累加到當天的三大法人合計
  let running = 0;
  const chartData = [...rows].reverse().map((r) => {
    running = round2(running + (r.total || 0));
    return { ...r, label: r.date.slice(5).replace("-", "/"), cum: running };
  });
  const sums = Object.fromEntries(
    [...WHO.map(({ key }) => key), "total"].map((k) => [k, round2(rows.reduce((s, r) => s + (r[k] || 0), 0))])
  );

  return (
    <div className="modal-overlay" onClick={onClose}>
    <div className="modal-box inst-history" onClick={(e) => e.stopPropagation()}>
      <div className="inst-history-head">
        <h3>📊 法人買賣超歷史</h3>
        <button className="inst-history-close" onClick={onClose} aria-label="關閉">✕</button>
      </div>
      <div className="inst-history-controls">
        <div className="ranking-tabs">
          {[20, 60].map((d) => (
            <button key={d} className={`ranking-tab ${days === d ? "active" : ""}`} onClick={() => setDays(d)}>
              近 {d} 日
            </button>
          ))}
        </div>
        <div className="ranking-tabs">
          {MARKETS.map((m) => (
            <button key={m.label} className={`ranking-tab ${market === m.key ? "active" : ""}`} onClick={() => setMarket(m.key)}>
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {records === null ? (
        <p className="loading-hint">載入中...</p>
      ) : error ? (
        <p className="error">{error}</p>
      ) : rows.length === 0 ? (
        <p className="no-data">暫無歷史資料</p>
      ) : (
        <>
          <div className="inst-history-sums">
            {WHO.map(({ key, label }) => (
              <span key={key}>{label}累計 <b className={upDown(sums[key])}>{fmt(sums[key])}</b> 億</span>
            ))}
            <span>三大法人合計 <b className={upDown(sums.total)}>{fmt(sums.total)}</b> 億</span>
          </div>

          {/* 自訂圖例放在圖表上方，比 recharts 內建的小字圖例好認 */}
          <div className="inst-legend">
            {WHO.map(({ key, label, color }) => (
              <span key={key}><i className="inst-legend-bar" style={{ background: color }} />{label}（單日，左軸）</span>
            ))}
            <span><i className="inst-legend-line" style={{ background: CUM_COLOR }} />三大法人累計（右軸）</span>
          </div>

          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={chartData} margin={{ top: 8, right: 0, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis yAxisId="day" tick={{ fontSize: 11 }} width={50} />
              {/* 累計值跟單日差一個量級，放右軸才看得出單日長條 */}
              <YAxis yAxisId="cum" orientation="right" tick={{ fontSize: 11, fill: CUM_COLOR }} width={60} />
              <Tooltip
                formatter={(v, name) => [`${fmt(v)} 億`, name]}
                contentStyle={{ background: "#111827", border: "1px solid #333" }}
              />
              <ReferenceLine yAxisId="day" y={0} stroke="#666" />
              {WHO.map(({ key, label, color }) => (
                <Bar key={key} yAxisId="day" dataKey={key} name={label} fill={color} />
              ))}
              <Line yAxisId="cum" type="monotone" dataKey="cum" name="三大法人累計"
                stroke={CUM_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>

          <div className="ranking-table-wrap">
            <table className="result-table inst-history-table">
              <thead>
                <tr>
                  <th>日期</th>
                  {WHO.map(({ key, label }) => <th key={key}>{label}(億)</th>)}
                  <th>合計(億)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.date}>
                    <td>{r.date}</td>
                    {WHO.map(({ key }) => <td key={key} className={upDown(r[key])}>{fmt(r[key])}</td>)}
                    <td className={upDown(r.total)}><b>{fmt(r.total)}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
    </div>
  );
}
