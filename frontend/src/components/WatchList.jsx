import { useState, useEffect } from "react";
import { getStock } from "../api";

export default function WatchList({ watchlist, watchNotes = {}, onRemove, onSelect, onUpdateNote }) {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(false);
  // 追蹤哪個 ticker 正在編輯備注
  const [editingTicker, setEditingTicker] = useState(null);
  const [editingNote, setEditingNote] = useState("");

  useEffect(() => {
    if (!watchlist.length) { setStocks([]); return; }
    const fetchAll = async () => {
      setLoading(true);
      const results = await Promise.allSettled(watchlist.map((t) => getStock(t)));
      setStocks(
        results
          .map((r, i) => r.status === "fulfilled" ? r.value.data : { ticker: watchlist[i], name: "—", price: null })
          .filter(Boolean)
      );
      setLoading(false);
    };
    fetchAll();
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
      <h2>自選清單</h2>

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
              <th>殖利率</th>
              <th>52週高</th>
              <th>52週低</th>
              <th>備注</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {stocks.map((s) => (
              <tr key={s.ticker}>
                <td>{s.ticker}</td>
                <td>{s.name}</td>
                <td>{s.price ?? "—"}</td>
                <td>{s.dividend_yield ? `${s.dividend_yield}%` : "—"}</td>
                <td>{s.week_52_high ?? "—"}</td>
                <td>{s.week_52_low ?? "—"}</td>
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
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
