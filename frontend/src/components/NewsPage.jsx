import { useState, useEffect, useMemo } from "react";
import { getHotNews, getNewsSummary } from "../api";

function formatPubDate(pubDate) {
  if (!pubDate) return "";
  const d = new Date(pubDate);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-TW", { timeZone: "Asia/Taipei", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

const OTHER_TAG = "其他";

export default function NewsPage({ onSelectStock }) {
  const [news, setNews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [tagFilter, setTagFilter] = useState("all");
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

  const tags = useMemo(() => [...new Set(news.map((n) => n.tag || OTHER_TAG))], [news]);
  const filtered = tagFilter === "all" ? news : news.filter((n) => (n.tag || OTHER_TAG) === tagFilter);

  const goStock = (e, code) => {
    e.preventDefault();
    e.stopPropagation();
    onSelectStock?.(code);
  };

  return (
    <div className="page news-page">
      <div className="news-header">
        <h2>台股新聞</h2>
        <div className="news-header-right">
          {updatedAt && <span className="news-updated">更新 {updatedAt}</span>}
          <button className="tl-refresh" onClick={load} title="重新整理">↻</button>
        </div>
      </div>

      {summary && (
        <div className="analysis-section">
          <div className="analysis-header">
            <h3>今日新聞重點</h3>
            <span className="news-updated">{summary.date}</span>
          </div>
          <div className="analysis-content">
            {summary.summary.split("\n").map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>

          {summary.stock_watch?.length > 0 && (
            <>
              <h3 className="paper-section-title">台股觀察</h3>
              <div className="stock-watch-list">
                {summary.stock_watch.map((s) => (
                  <a
                    key={s.code}
                    className="stock-watch-item"
                    href={s.link}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <span className="stock-watch-code" onClick={(e) => goStock(e, s.code)}>
                      {s.name}({s.code})
                    </span>
                    <span className="stock-watch-headline">{s.headline}</span>
                  </a>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {tags.length > 0 && (
        <div className="news-source-tabs">
          <button
            className={tagFilter === "all" ? "active" : ""}
            onClick={() => setTagFilter("all")}
          >
            全部
          </button>
          {tags.map((t) => (
            <button
              key={t}
              className={tagFilter === t ? "active" : ""}
              onClick={() => setTagFilter(t)}
            >
              {t}
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
              {n.tag && <span className="news-item-source">{n.tag}</span>}
              {n.title}
              {n.stocks?.length > 0 && (
                <span className="news-item-stocks">
                  {n.stocks.map((s) => (
                    <span key={s.code} className="news-item-stock" onClick={(e) => goStock(e, s.code)}>
                      {s.name}({s.code})
                    </span>
                  ))}
                </span>
              )}
            </span>
            <span className="news-item-date">{formatPubDate(n.pub_date)}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
