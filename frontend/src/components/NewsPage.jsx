import { useState, useEffect } from "react";
import { getHotNews } from "../api";

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

  const load = () => {
    setLoading(true);
    setError(null);
    getHotNews(30)
      .then((res) => {
        setNews(res.data.news || []);
        setUpdatedAt(new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" }));
      })
      .catch((e) => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="page news-page">
      <div className="news-header">
        <h2>熱門新聞</h2>
        <div className="news-header-right">
          {updatedAt && <span className="news-updated">更新 {updatedAt}</span>}
          <button className="tl-refresh" onClick={load} title="重新整理">↻</button>
        </div>
      </div>

      {loading && <p className="news-loading">載入中...</p>}
      {error && <p className="error">❌ {error}</p>}

      {!loading && !error && news.length === 0 && (
        <p className="news-empty">暫無新聞</p>
      )}

      <div className="news-list">
        {news.map((n, i) => (
          <a
            key={i}
            className="news-item"
            href={n.link}
            target="_blank"
            rel="noopener noreferrer"
          >
            <span className="news-item-title">{n.title}</span>
            <span className="news-item-date">{formatPubDate(n.pub_date)}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
