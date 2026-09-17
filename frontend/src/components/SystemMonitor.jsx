import { useState, useEffect } from "react";
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
            <h3 className="paper-section-title">💾 資料庫</h3>
            <div className="market-link-list">
              <div className="market-link-row">
                <span>檔案大小</span>
                <span className="market-link-count">{data.db_size_mb} MB</span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
