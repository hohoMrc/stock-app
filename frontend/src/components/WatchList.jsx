import { useState, useEffect, useRef } from "react";
import { getStock } from "../api";
import { isTradingHours } from "../marketHours";

export default function WatchList({ watchlist, watchNotes = {}, watchAddedAt = {}, onRemove, onSelect, onUpdateNote }) {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [live, setLive] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(null);
  const pollRef = useRef(null);
  // 追蹤哪個 ticker 正在編輯備注
  const [editingTicker, setEditingTicker] = useState(null);
  const [editingNote, setEditingNote] = useState("");

  const fetchAll = async (silent = false) => {
    if (!watchlist.length) { setStocks([]); return; }
    if (!silent) setLoading(true);
    const results = await Promise.allSettled(watchlist.map((t) => getStock(t)));
    setStocks(
      results
        .map((r, i) => r.status === "fulfilled" ? r.value.data : { ticker: watchlist[i], name: "—", price: null })
        .filter(Boolean)
    );
    setUpdatedAt(new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    if (!silent) setLoading(false);
  };

  useEffect(() => {
    fetchAll();
    clearInterval(pollRef.current);
    setLive(isTradingHours());
    pollRef.current = setInterval(() => {
      if (!isTradingHours()) { setLive(false); return; }
      setLive(true);
      fetchAll(true);
    }, 30_000);
    return () => clearInterval(pollRef.current);
  }, [watchlist]);

  const startEdit = (ticker) => {
    setEditingTicker(ticker);
    setEditingNote(watchNotes[ticker] || "");
  };

  const commitEdit = (ticker) => {
    if (onUpdateNote) onUpdateNote(ticker, editingNote);
    setEditingTicker(null);
  };

  return (
    <div className="page">
      <div className="watchlist-header-row">
        <h2>自選清單</h2>
        {live && <span className="live-dot" title="即時自動更新中">● 即時</span>}
        {updatedAt && <span className="watchlist-updated">更新 {updatedAt}</span>}
      </div>

      {watchlist.length === 0 ? (
        <div className="empty-watchlist">
          <p>尚未加入任何股票</p>
          <p className="empty-hint">在「個股查詢」頁點擊 ★ 加入觀察</p>
        </div>
      ) : loading ? (
        <p className="loading-hint">載入中...</p>
      ) : (
        <table className="result-table">
          <thead>
            <tr>
              <th>代號</th>
              <th>名稱</th>
              <th>股價</th>
              <th>漲跌</th>
              <th>漲跌幅</th>
              <th>加入日期</th>
              <th>備注</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {stocks.map((s) => {
              const up   = s.change > 0;
              const down = s.change < 0;
              const sign = up ? "+" : "";
              const dir  = up ? "up" : down ? "down" : "";
              return (
              <tr key={s.ticker} className={up ? "row-up" : down ? "row-down" : ""}>
                <td>{s.ticker}</td>
                <td>{s.name}</td>
                <td>{s.price ?? "—"}</td>
                <td className={dir}>{s.change != null ? `${sign}${s.change}` : "—"}</td>
                <td className={dir}>{s.change_pct != null ? `${sign}${s.change_pct}%` : "—"}</td>
                <td>
                  {watchAddedAt[s.ticker]
                    ? new Date(watchAddedAt[s.ticker] * 1000).toLocaleDateString("zh-TW")
                    : "—"}
                </td>
                <td className="note-cell">
                  {editingTicker === s.ticker ? (
                    <input
                      className="note-input"
                      autoFocus
                      value={editingNote}
                      onChange={(e) => setEditingNote(e.target.value)}
                      onBlur={() => commitEdit(s.ticker)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitEdit(s.ticker);
                        if (e.key === "Escape") setEditingTicker(null);
                      }}
                    />
                  ) : (
                    <span
                      className="note-text"
                      onClick={() => onUpdateNote && startEdit(s.ticker)}
                      title="點擊編輯備注"
                    >
                      {watchNotes[s.ticker] || <span className="note-placeholder">點擊新增</span>}
                    </span>
                  )}
                </td>
                <td className="watchlist-actions">
                  <button className="view-btn" onClick={() => onSelect(s.ticker)}>查看</button>
                  <button className="remove-btn" onClick={() => onRemove(s.ticker)}>移除</button>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
