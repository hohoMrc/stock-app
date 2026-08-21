import { useState, useEffect, useRef } from "react";
import { getStock } from "../api";
import { isTradingHours } from "../marketHours";

export default function WatchList({
  watchlist, watchNotes = {}, watchAddedAt = {}, watchGroups = [], watchGroupByTicker = {},
  onRemove, onSelect, onUpdateNote, onRenameGroup, onMoveGroup,
}) {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [live, setLive] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(null);
  const pollRef = useRef(null);
  // 追蹤哪個 ticker 正在編輯備注
  const [editingTicker, setEditingTicker] = useState(null);
  const [editingNote, setEditingNote] = useState("");
  // 分組頁籤：目前選的分組（"all" 或 group_id），以及正在重新命名的分組
  const [activeGroup, setActiveGroup] = useState("all");
  const [renamingGroupId, setRenamingGroupId] = useState(null);
  const [renamingName, setRenamingName] = useState("");

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

  const startRenameGroup = (g) => {
    setRenamingGroupId(g.group_id);
    setRenamingName(g.name);
  };

  const commitRenameGroup = () => {
    const name = renamingName.trim();
    if (name && onRenameGroup) onRenameGroup(renamingGroupId, name);
    setRenamingGroupId(null);
  };

  const countByGroup = {};
  watchlist.forEach((t) => {
    const gid = watchGroupByTicker[t] || 1;
    countByGroup[gid] = (countByGroup[gid] || 0) + 1;
  });

  const filteredStocks = activeGroup === "all"
    ? stocks
    : stocks.filter((s) => (watchGroupByTicker[s.ticker] || 1) === activeGroup);

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
        <>
          <div className="ranking-tabs watchlist-group-tabs">
            <button
              className={`ranking-tab ${activeGroup === "all" ? "active" : ""}`}
              onClick={() => setActiveGroup("all")}
            >
              全部（{watchlist.length}）
            </button>
            {watchGroups.map((g) => (
              renamingGroupId === g.group_id ? (
                <input
                  key={g.group_id}
                  className="group-rename-input"
                  autoFocus
                  value={renamingName}
                  onChange={(e) => setRenamingName(e.target.value)}
                  onBlur={commitRenameGroup}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitRenameGroup();
                    if (e.key === "Escape") setRenamingGroupId(null);
                  }}
                />
              ) : (
                <button
                  key={g.group_id}
                  className={`ranking-tab ${activeGroup === g.group_id ? "active" : ""}`}
                  onClick={() => setActiveGroup(g.group_id)}
                  onDoubleClick={() => startRenameGroup(g)}
                  title="雙擊可重新命名分組"
                >
                  {g.name}（{countByGroup[g.group_id] || 0}）
                </button>
              )
            ))}
          </div>

          {filteredStocks.length === 0 ? (
            <p className="no-data">這個分組還沒有股票</p>
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
                <th>分組</th>
                <th>備注</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredStocks.map((s) => {
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
                  <td>
                    <select
                      className="group-select"
                      value={watchGroupByTicker[s.ticker] || 1}
                      onChange={(e) => onMoveGroup && onMoveGroup(s.ticker, parseInt(e.target.value, 10))}
                    >
                      {watchGroups.map((g) => (
                        <option key={g.group_id} value={g.group_id}>{g.name}</option>
                      ))}
                    </select>
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
        </>
      )}
    </div>
  );
}
