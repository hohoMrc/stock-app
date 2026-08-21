import { useState, useEffect, useRef } from "react";
import { getStock } from "../api";
import { isTradingHours } from "../marketHours";

// 後端不同來源回傳的交易所欄位有的是原始代碼（TW/TWO），有的已經是中文，統一轉成手機版卡片用的縮寫
const EXCHANGE_TAG = { TW: "市", TWO: "櫃", "上市": "市", "上櫃": "櫃" };

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
          <div className="sticky-name-table">
          <div className="ranking-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                <th className="col-ticker">代號</th>
                <th className="col-name">名稱</th>
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
                <tr
                  key={s.ticker}
                  className={`industry-row-clickable ${up ? "row-up" : down ? "row-down" : ""}`}
                  onClick={() => onSelect(s.ticker)}
                >
                  <td className="col-ticker">{s.ticker}</td>
                  <td className="col-name">
                    <span className="col-name-full">{s.name}</span>
                    <span className="col-name-short">
                      {s.name && s.name.length > 4 ? `${s.name.slice(0, 4)}...` : s.name}
                    </span>
                    <span className="col-name-sub">
                      {s.exchange && (
                        <span className="mrc-exchange-tag">{EXCHANGE_TAG[s.exchange] ?? s.exchange}</span>
                      )}
                      <span className="mrc-ticker">{s.ticker}</span>
                    </span>
                  </td>
                  <td>{s.price ?? "—"}</td>
                  <td className={dir}>{s.change != null ? `${sign}${s.change}` : "—"}</td>
                  <td className={dir}>{s.change_pct != null ? `${sign}${s.change_pct}%` : "—"}</td>
                  <td>
                    {watchAddedAt[s.ticker]
                      ? new Date(watchAddedAt[s.ticker] * 1000).toLocaleDateString("zh-TW")
                      : "—"}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
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
                  <td className="note-cell" onClick={(e) => e.stopPropagation()}>
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
                  <td className="watchlist-actions" onClick={(e) => e.stopPropagation()}>
                    <button className="remove-btn" onClick={() => onRemove(s.ticker)}>移除</button>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
          </div>
          </div>
          )}
        </>
      )}
    </div>
  );
}
