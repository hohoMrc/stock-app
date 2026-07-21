import { useState, useEffect, useMemo } from "react";
import { getHotNews, getNewsSummary } from "../api";

function formatPubDate(pubDate) {
  if (!pubDate) return "";
  const d = new Date(pubDate);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-TW", { timeZone: "Asia/Taipei", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function NewsPage() {
  const [news, setNews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [sourceFilter, setSourceFilter] = useState("all");
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    getNewsSummary()
      .then((res) => { if (res.data?.summary) setSummary(res.data); })
      .catch(() => {});
  }, []);

  const load = () => {
    setLoading(true);
    setError(null);
    getHotNews(50)
      .then((res) => {
        setNews(res.data.news || []);
        setUpdatedAt(new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" }));
      })
      .catch((e) => {
        const detail = e?.response?.data?.detail;
        // FastAPI 422 驗證錯誤的 detail 是物件陣列，不能直接當 JSX 顯示，只能用 e.message 代替
        setError(typeof detail === "string" ? detail : e.message);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const sources = useMemo(() => [...new Set(news.map((n) => n.source))], [news]);
  const filtered = sourceFilter === "all" ? news : news.filter((n) => n.source === sourceFilter);

  return (
    <div className="page news-page">
      <div className="news-header">
        <h2>熱門新聞</h2>
        <div className="news-header-right">
          {updatedAt && <span className="news-updated">更新 {updatedAt}</span>}
          <button className="tl-refresh" onClick={load} title="重新整理">↻</button>
        </div>
      </div>

      {summary && (
        <div className="analysis-section">
          <div className="analysis-header">
            <h3>今日新聞重點與台股觀察</h3>
            <span className="news-updated">{summary.date}</span>
          </div>
          <div className="analysis-content">
            {summary.summary.split("\n").map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>
        </div>
      )}

      {sources.length > 0 && (
        <div className="news-source-tabs">
          <button
            className={sourceFilter === "all" ? "active" : ""}
            onClick={() => setSourceFilter("all")}
          >
            全部
          </button>
          {sources.map((s) => (
            <button
              key={s}
              className={sourceFilter === s ? "active" : ""}
              onClick={() => setSourceFilter(s)}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {loading && <p className="news-loading">載入中...</p>}
      {error && <p className="error">❌ {error}</p>}

      {!loading && !error && filtered.length === 0 && (
        <p className="news-empty">暫無新聞</p>
      )}

      <div className="news-list">
        {filtered.map((n, i) => (
          <a
            key={i}
            className="news-item"
            href={n.link}
            target="_blank"
            rel="noopener noreferrer"
          >
            <span className="news-item-title">
              {n.source && <span className="news-item-source">{n.source}</span>}
              {n.title}
            </span>
            <span className="news-item-date">{formatPubDate(n.pub_date)}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
