import { useState, useEffect } from "react";
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from "recharts";
import { getSystemStatus } from "../api";

const SCAN_LABELS = {
  bird_beak: "MA黏合",
  weekly_surge: "週漲幅急漲",
};

const FRESHNESS_LABELS = {
  candles: "股票日K",
  institutional_trades: "三大法人",
  news_summaries: "新聞摘要",
};

const PIE_COLORS = ["#60a5fa", "#fbbf24", "#4ade80", "#f87171", "#a78bfa", "#34d399", "#94a3b8"];

function daysAgo(dateStr) {
  if (!dateStr) return null;
  const diffMs = new Date().setHours(0, 0, 0, 0) - new Date(dateStr).setHours(0, 0, 0, 0);
  return Math.round(diffMs / 86400000);
}

export default function SystemMonitor() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = () => {
    setLoading(true);
    setError(null);
    getSystemStatus()
      .then((res) => setData(res.data))
      .catch((e) => setError(e?.response?.data?.detail || "載入失敗"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="page">
      <div className="ranking-header">
        <h2>系統監控</h2>
        <button className="refresh-btn" onClick={load} disabled={loading}>
          {loading ? "更新中..." : "↻ 重新整理"}
        </button>
      </div>

      {error && <p className="error">❌ {error}</p>}
      {loading && !data && <p className="loading-hint">載入中...</p>}

      {data && (
        <>
          <div className="stock-card market-panel">
            <h3 className="paper-section-title">📅 資料新鮮度</h3>
            <div className="info-grid">
              {Object.entries(FRESHNESS_LABELS).map(([key, label]) => {
                const date = data.data_freshness?.[key];
                const n = daysAgo(date);
                return (
                  <div key={key} className="info-item">
                    <span className="info-label">{label}</span>
                    <span className="info-value">{date ?? "—"}</span>
                    <span className="info-label">{n == null ? "" : `距今 ${n} 天`}</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="stock-card market-panel">
            <h3 className="paper-section-title">📊 近14日掃描訊號趨勢</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.daily_scan_counts || []} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) => {
                    const [, m, d] = v.split("-");
                    return `${parseInt(m)}/${parseInt(d)}`;
                  }}
                />
                <YAxis tick={{ fontSize: 11 }} width={30} allowDecimals={false} />
                <Tooltip
                  labelFormatter={(l) => {
                    const [y, m, d] = l.split("-");
                    return `${y}年${parseInt(m)}月${parseInt(d)}日`;
                  }}
                  formatter={(v, name) => [`${v} 檔`, SCAN_LABELS[name] ?? name]}
                />
                <Legend formatter={(name) => SCAN_LABELS[name] ?? name} />
                <Bar dataKey="bird_beak" name="bird_beak" fill="#60a5fa" />
                <Bar dataKey="weekly_surge" name="weekly_surge" fill="#fbbf24" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="stock-card market-panel">
            <h3 className="paper-section-title">📋 掃描訊號</h3>
            <div className="market-link-list">
              {(data.scans || []).map((s) => (
                <div key={s.scan_type} className="market-link-row">
                  <span>{SCAN_LABELS[s.scan_type] ?? s.scan_type}</span>
                  <span className="market-link-count">
                    {s.latest_date ?? "—"}（{s.latest_count ?? 0} 筆）
                  </span>
                </div>
              ))}
              {(!data.scans || data.scans.length === 0) && (
                <p className="no-data">目前沒有掃描紀錄</p>
              )}
            </div>
          </div>

          <div className="stock-card market-panel">
            <h3 className="paper-section-title">💾 資料庫（共 {data.db_size_mb} MB）</h3>
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={data.table_sizes || []}
                  dataKey="mb"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                >
                  {(data.table_sizes || []).map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => [`${v} MB`, ""]} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
