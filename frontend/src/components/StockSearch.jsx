import { useState, useRef, useEffect } from "react";
import { getStock, searchStocks } from "../api";

// 搜尋紀錄存在瀏覽器 localStorage，最多保留 10 檔（最新的在最前面）
const HISTORY_KEY = "stockSearchHistory";
const HISTORY_MAX = 10;

function loadHistory() {
  try {
    const arr = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(arr) ? arr.filter((h) => h && h.ticker) : [];
  } catch {
    return [];
  }
}

function saveHistory(list) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(list)); } catch { /* 無痕模式等情況寫不進去就算了 */ }
}

export default function StockSearch({ onSelect }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [history, setHistory] = useState(loadHistory);
  // 下拉目前顯示的是「搜尋紀錄」還是「搜尋建議」
  const [showHistory, setShowHistory] = useState(false);
  const debounceRef = useRef(null);
  const wrapperRef = useRef(null);
  // 注音／倉頡等輸入法選字中（還沒按空白或 Enter 確定）就不要送搜尋
  const composingRef = useRef(false);

  // 點擊外部關閉下拉
  useEffect(() => {
    const handler = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setShowSuggestions(false);
        setShowHistory(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const runSuggest = (val) => {
    clearTimeout(debounceRef.current);
    const q = val.trim();
    if (q.length < 1) {
      setSuggestions([]);
      setShowSuggestions(false);
      // 清空輸入框時改回顯示搜尋紀錄
      setShowHistory(history.length > 0);
      return;
    }
    setShowHistory(false);
    // 100ms debounce，讓建議更快出現
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await searchStocks(q);
        setSuggestions(res.data.results);
        setShowSuggestions(res.data.results.length > 0);
      } catch {
        setSuggestions([]);
      }
    }, 100);
  };

  const handleInputChange = (e) => {
    const val = e.target.value;
    setInput(val);
    // 選字中的注音（例如「ㄊㄞˊ」）不是真正的關鍵字，等 compositionend 再搜
    if (composingRef.current || e.nativeEvent.isComposing) return;
    runSuggest(val);
  };

  const handleCompositionEnd = (e) => {
    composingRef.current = false;
    // 選完字後用確定的文字搜尋（有些瀏覽器 compositionend 會比最後一次 onChange 晚到）
    runSuggest(e.currentTarget.value);
  };

  const addHistory = (ticker, name) => {
    setHistory((prev) => {
      const old = prev.find((h) => h.ticker === ticker);
      const entry = { ticker, name: name || old?.name || "" };
      const next = [entry, ...prev.filter((h) => h.ticker !== ticker)].slice(0, HISTORY_MAX);
      saveHistory(next);
      return next;
    });
  };

  const removeHistory = (ticker) => {
    setHistory((prev) => {
      const next = prev.filter((h) => h.ticker !== ticker);
      saveHistory(next);
      if (!next.length) setShowHistory(false);
      return next;
    });
  };

  const clearHistory = () => {
    saveHistory([]);
    setHistory([]);
    setShowHistory(false);
  };

  const handleFocus = () => {
    if (input.trim()) {
      if (suggestions.length > 0) setShowSuggestions(true);
    } else if (history.length > 0) {
      setShowHistory(true);
    }
  };

  const handleSelect = (ticker, name) => {
    addHistory(ticker, name);
    setInput(ticker);
    setSuggestions([]);
    setShowSuggestions(false);
    setShowHistory(false);
    // 建議清單來的代號已確定有效，直接跳轉到股價走勢頁，不用再多按一次
    onSelect(ticker);
  };

  const handleSearch = () => {
    if (!input.trim()) return;
    // 有建議且第一筆代號完全符合輸入 → 直接用它；否則若有建議清單先選第一筆
    if (suggestions.length > 0) {
      const pick = suggestions.find((s) => s.ticker === input.trim()) || suggestions[0];
      handleSelect(pick.ticker, pick.name);
      return;
    }
    setShowSuggestions(false);
    setShowHistory(false);
    fetchStock(input.trim());
  };

  const fetchStock = async (ticker) => {
    setLoading(true);
    setError("");
    try {
      const res = await getStock(ticker);
      // 驗證代號有效後直接跳轉到股價走勢頁
      addHistory(res.data.ticker, res.data.name);
      onSelect(res.data.ticker);
    } catch (e) {
      setError(e.response?.data?.detail || "查詢失敗，請確認股票代號");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <h2>個股查詢</h2>
      <div className="search-bar" ref={wrapperRef} style={{ position: "relative" }}>
        <input
          type="text"
          placeholder="輸入代號或股名（例：2330 或 台積電）"
          value={input}
          onChange={handleInputChange}
          onKeyDown={(e) => {
            // 輸入法選字時按 Enter 是「確定這個字」，不是送出查詢
            if (e.key === "Enter" && !e.nativeEvent.isComposing && !composingRef.current) handleSearch();
          }}
          onCompositionStart={() => { composingRef.current = true; }}
          onCompositionEnd={handleCompositionEnd}
          onFocus={handleFocus}
          onClick={handleFocus}
          autoComplete="off"
        />
        <button onClick={handleSearch} disabled={loading}>
          {loading ? "查詢中..." : "查詢"}
        </button>

        {showSuggestions && (
          <ul className="search-suggestions">
            {suggestions.map((s) => (
              <li key={s.ticker} onMouseDown={() => handleSelect(s.ticker, s.name)}>
                <span className="sug-ticker">{s.ticker}</span>
                <span className="sug-name">{s.name}</span>
              </li>
            ))}
          </ul>
        )}

        {showHistory && !showSuggestions && history.length > 0 && (
          <ul className="search-suggestions">
            <li className="sug-history-header" onMouseDown={(e) => e.preventDefault()}>
              <span>最近搜尋</span>
              <button type="button" className="sug-history-clear" onMouseDown={(e) => { e.preventDefault(); clearHistory(); }}>
                清除全部
              </button>
            </li>
            {history.map((h) => (
              <li key={h.ticker} onMouseDown={() => handleSelect(h.ticker, h.name)}>
                <span className="sug-ticker">{h.ticker}</span>
                <span className="sug-name">{h.name}</span>
                <button
                  type="button"
                  className="sug-history-remove"
                  title="從紀錄移除"
                  onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); removeHistory(h.ticker); }}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && <p className="error">{error}</p>}
    </div>
  );
}
