import { useState, useEffect } from "react";
import StockSearch from "./components/StockSearch";
import StockDetail from "./components/StockDetail";
import StockScreener from "./components/StockScreener";
import IndustryStocks from "./components/IndustryStocks";
import WatchList from "./components/WatchList";
import "./App.css";

const DEFAULT_TICKERS = [
  "2330", "2303", "2454", "3711", "2379", "2344", "2408",
  "2317", "2357", "2308", "2382", "2395", "3008", "2301", "2327",
  "2412", "4904", "3045",
  "2882", "2881", "2891", "2886", "2884",
  "1301", "1303", "1326", "2002", "1101",
  "2481", "3588", "6168", "6226", "6243", "6573", "6834",
];

const INIT_FILTERS = {
  min_price: "", max_price: "",
  min_volume: "",
  min_market_cap: "", max_market_cap: "",
  min_capital: "",
  min_pe: "", max_pe: "",
  min_dividend_yield: "",
  min_weekly_change: "",
  near_ma: "", near_ma_pct: "3",
  pattern: "",
  custom_tickers: "",
};

export default function App() {
  const [activePage, setActivePage] = useState("search");
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [selectedIndustry, setSelectedIndustry] = useState(null);
  const [prevPage, setPrevPage] = useState("search");

  // 篩選頁狀態提升，切頁後不遺失
  const [screenerFilters, setScreenerFilters] = useState(INIT_FILTERS);
  const [screenerResults, setScreenerResults] = useState([]);
  const [screenerSearched, setScreenerSearched] = useState(false);

  // 自選清單（localStorage 持久化）
  const [watchlist, setWatchlist] = useState(() => {
    try { return JSON.parse(localStorage.getItem("watchlist") || "[]"); }
    catch { return []; }
  });
  useEffect(() => {
    localStorage.setItem("watchlist", JSON.stringify(watchlist));
  }, [watchlist]);
  const toggleWatch = (ticker) => {
    setWatchlist((prev) =>
      prev.includes(ticker) ? prev.filter((t) => t !== ticker) : [...prev, ticker]
    );
  };

  const handleSelectStock = (ticker, from = "search") => {
    setSelectedTicker(ticker);
    setPrevPage(from);
    setActivePage("detail");
  };

  const handleSelectIndustry = (industry, fromTicker) => {
    setSelectedIndustry({ name: industry, excludeTicker: fromTicker });
    setPrevPage("detail");
    setActivePage("industry");
  };

  return (
    <div className="app">
      <header className="header">
        <h1>台股分析工具</h1>
        <nav className="top-nav">
          <button
            className={["search", "detail", "industry"].includes(activePage) ? "active" : ""}
            onClick={() => setActivePage("search")}
          >
            個股查詢
          </button>
          <button
            className={activePage === "screener" ? "active" : ""}
            onClick={() => setActivePage("screener")}
          >
            選股篩選
          </button>
          <button
            className={activePage === "watchlist" ? "active" : ""}
            onClick={() => setActivePage("watchlist")}
          >
            自選清單
            {watchlist.length > 0 && (
              <span className="watch-count">{watchlist.length}</span>
            )}
          </button>
        </nav>
      </header>

      <main className="main">
        {activePage === "search" && (
          <StockSearch onSelect={(t) => handleSelectStock(t, "search")} />
        )}
        {activePage === "detail" && selectedTicker && (
          <StockDetail
            ticker={selectedTicker}
            onBack={() => setActivePage(prevPage)}
            onIndustry={handleSelectIndustry}
            watchlist={watchlist}
            onToggleWatch={toggleWatch}
          />
        )}
        {activePage === "industry" && selectedIndustry && (
          <IndustryStocks
            industry={selectedIndustry.name}
            excludeTicker={selectedIndustry.excludeTicker}
            onSelect={(t) => handleSelectStock(t, "industry")}
            onBack={() => setActivePage(prevPage)}
          />
        )}
        {activePage === "watchlist" && (
          <WatchList
            watchlist={watchlist}
            onRemove={toggleWatch}
            onSelect={(t) => handleSelectStock(t, "watchlist")}
          />
        )}
        {/* 保持 DOM 存在（display:none 效果），避免切頁時狀態消失 */}
        <div style={{ display: activePage === "screener" ? "block" : "none" }}>
          <StockScreener
            filters={screenerFilters}
            setFilters={setScreenerFilters}
            results={screenerResults}
            setResults={setScreenerResults}
            searched={screenerSearched}
            setSearched={setScreenerSearched}
            onSelect={(t) => handleSelectStock(t, "screener")}
          />
        </div>
      </main>

      {/* 手機底部導覽列 */}
      <nav className="bottom-nav">
        <button
          className={["search", "detail", "industry"].includes(activePage) ? "active" : ""}
          onClick={() => setActivePage("search")}
        >
          <span className="bottom-nav-icon">🔍</span>
          <span className="bottom-nav-label">個股</span>
        </button>
        <button
          className={activePage === "screener" ? "active" : ""}
          onClick={() => setActivePage("screener")}
        >
          <span className="bottom-nav-icon">📊</span>
          <span className="bottom-nav-label">篩選</span>
        </button>
        <button
          className={activePage === "watchlist" ? "active" : ""}
          onClick={() => setActivePage("watchlist")}
        >
          <span className="bottom-nav-icon">⭐</span>
          <span className="bottom-nav-label">
            自選{watchlist.length > 0 && <span className="watch-count">{watchlist.length}</span>}
          </span>
        </button>
      </nav>
    </div>
  );
}
