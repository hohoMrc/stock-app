import { useState, useRef, useEffect } from "react";
import { getStock, searchStocks } from "../api";

export default function StockSearch({ onSelect }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const debounceRef = useRef(null);
  const wrapperRef = useRef(null);

  // 點擊外部關閉下拉
  useEffect(() => {
    const handler = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleInputChange = (e) => {
    const val = e.target.value;
    setInput(val);

    clearTimeout(debounceRef.current);
    if (val.trim().length < 1) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    // 100ms debounce，讓建議更快出現
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await searchStocks(val.trim());
        setSuggestions(res.data.results);
        setShowSuggestions(res.data.results.length > 0);
      } catch {
        setSuggestions([]);
      }
    }, 100);
  };

  const handleSelect = (ticker) => {
    setInput(ticker);
    setSuggestions([]);
    setShowSuggestions(false);
    // 建議清單來的代號已確定有效，直接跳轉到股價走勢頁，不用再多按一次
    onSelect(ticker);
  };

  const handleSearch = () => {
    if (!input.trim()) return;
    // 有建議且第一筆代號完全符合輸入 → 直接用它；否則若有建議清單先選第一筆
    if (suggestions.length > 0) {
      const exact = suggestions.find((s) => s.ticker === input.trim());
      handleSelect(exact ? exact.ticker : suggestions[0].ticker);
      return;
    }
    setShowSuggestions(false);
    fetchStock(input.trim());
  };

  const fetchStock = async (ticker) => {
    setLoading(true);
    setError("");
    try {
      const res = await getStock(ticker);
      // 驗證代號有效後直接跳轉到股價走勢頁
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
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
          autoComplete="off"
        />
        <button onClick={handleSearch} disabled={loading}>
          {loading ? "查詢中..." : "查詢"}
        </button>

        {showSuggestions && (
          <ul className="search-suggestions">
            {suggestions.map((s) => (
              <li key={s.ticker} onMouseDown={() => handleSelect(s.ticker)}>
                <span className="sug-ticker">{s.ticker}</span>
                <span className="sug-name">{s.name}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && <p className="error">{error}</p>}
    </div>
  );
}
