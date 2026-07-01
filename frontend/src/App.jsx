import { useState, useEffect } from "react";
import StockSearch from "./components/StockSearch";
import StockDetail from "./components/StockDetail";
import StockScreener from "./components/StockScreener";
import IndustryStocks from "./components/IndustryStocks";
import WatchList from "./components/WatchList";
import AuthModal from "./components/AuthModal";
import WatchNoteModal from "./components/WatchNoteModal";
import TradeValueRanking from "./components/TradeValueRanking";
import TradingTerminal from "./components/TradingTerminal";
import { fetchWatchlist, addWatch, removeWatch, updateWatchNote } from "./api";
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
  const [activePage, setActivePage] = useState("ranking");
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [selectedIndustry, setSelectedIndustry] = useState(null);
  const [pageHistory, setPageHistory] = useState([]);

  // 篩選頁狀態提升，切頁後不遺失
  const [screenerFilters, setScreenerFilters] = useState(INIT_FILTERS);
  const [screenerResults, setScreenerResults] = useState([]);
  const [screenerSearched, setScreenerSearched] = useState(false);

  // 帳號狀態
  const [username, setUsername] = useState(() => localStorage.getItem("username") || null);
  const [showAuth, setShowAuth] = useState(false);
  const [pendingWatch, setPendingWatch] = useState(null); // 等待填備注的 ticker
  const [menuOpen, setMenuOpen] = useState(false);

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    setUsername(null);
    setWatchlist([]);
    setWatchNotes({});
  };

  // 自選清單（登入後從後端同步，否則用 localStorage）
  const [watchlist, setWatchlist] = useState(() => {
    try { return JSON.parse(localStorage.getItem("watchlist") || "[]"); }
    catch { return []; }
  });
  const [watchNotes, setWatchNotes] = useState({});

  useEffect(() => {
    if (username) {
      fetchWatchlist()
        .then((res) => {
          setWatchlist(res.data.tickers);
          setWatchNotes(res.data.notes || {});
        })
        .catch(() => {});
    } else {
      localStorage.setItem("watchlist", JSON.stringify(watchlist));
    }
  }, [username]);

  const handleUpdateNote = async (ticker, note) => {
    setWatchNotes((prev) => ({ ...prev, [ticker]: note }));
    try { await updateWatchNote(ticker, note); } catch { /* ignore */ }
  };

  const toggleWatch = async (ticker) => {
    if (!username) { setShowAuth(true); return; }
    const has = watchlist.includes(ticker);
    if (has) {
      // 移除：直接執行
      setWatchlist((prev) => prev.filter((t) => t !== ticker));
      setWatchNotes((prev) => { const n = { ...prev }; delete n[ticker]; return n; });
      try { await removeWatch(ticker); } catch {
        setWatchlist((prev) => [...prev, ticker]);
      }
    } else {
      // 加入：先彈備注視窗
      setPendingWatch(ticker);
    }
  };

  const confirmAddWatch = async (ticker, note) => {
    setPendingWatch(null);
    setWatchlist((prev) => [...prev, ticker]);
    if (note) setWatchNotes((prev) => ({ ...prev, [ticker]: note }));
    try {
      await addWatch(ticker);
    } catch {
      // addWatch 失敗才 rollback
      setWatchlist((prev) => prev.filter((t) => t !== ticker));
      setWatchNotes((prev) => { const n = { ...prev }; delete n[ticker]; return n; });
      return;
    }
    // 備注儲存失敗不影響加入
    if (note) {
      try { await updateWatchNote(ticker, note); } catch { /* ignore */ }
    }
  };

  const goBack = () => {
    setPageHistory((prev) => {
      const history = [...prev];
      const target = history.pop() || "search";
      setActivePage(target);
      return history;
    });
  };

  const handleSelectStock = (ticker) => {
    setSelectedTicker(ticker);
    setPageHistory((prev) => [...prev, activePage]);
    setActivePage("detail");
  };

  const handleSelectIndustry = (industry, fromTicker) => {
    setSelectedIndustry({ name: industry, excludeTicker: fromTicker });
    setPageHistory((prev) => [...prev, activePage]);
    setActivePage("industry");
  };

  return (
    <div className="app">
      <header className="header">
        <h1>台股分析工具</h1>

        {/* 桌機版：帳號區 + 導覽 */}
        <div className="header-right desktop-only">
          {username ? (
            <div className="user-info">
              <span className="user-email">{username}</span>
              <button className="logout-btn" onClick={logout}>登出</button>
            </div>
          ) : (
            <button className="login-btn" onClick={() => setShowAuth(true)}>登入 / 註冊</button>
          )}
        </div>
        <nav className="top-nav desktop-only">
          <button
            className={activePage === "terminal" ? "active" : ""}
            onClick={() => setActivePage("terminal")}
          >
            看盤
          </button>
          <button
            className={activePage === "ranking" ? "active" : ""}
            onClick={() => setActivePage("ranking")}
          >
            排行榜
          </button>
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

        {/* 手機版：漢堡按鈕 */}
        <button
          className="hamburger-btn mobile-only"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label="選單"
        >
          {menuOpen ? "✕" : "☰"}
        </button>

        {/* 手機版：展開選單 */}
        {menuOpen && (
          <div className="mobile-menu" onClick={() => setMenuOpen(false)}>
            <button
              className={["search", "detail", "industry"].includes(activePage) ? "active" : ""}
              onClick={() => setActivePage("search")}
            >個股查詢</button>
            <button
              className={activePage === "screener" ? "active" : ""}
              onClick={() => setActivePage("screener")}
            >選股篩選</button>
            <button
              className={activePage === "watchlist" ? "active" : ""}
              onClick={() => setActivePage("watchlist")}
            >
              自選清單{watchlist.length > 0 && <span className="watch-count">{watchlist.length}</span>}
            </button>
            <button
              className={activePage === "ranking" ? "active" : ""}
              onClick={() => setActivePage("ranking")}
            >成交值排行</button>
            <div className="mobile-menu-divider" />
            {username ? (
              <>
                <span className="mobile-menu-user">{username}</span>
                <button className="mobile-menu-logout" onClick={logout}>登出</button>
              </>
            ) : (
              <button className="mobile-menu-login" onClick={() => setShowAuth(true)}>登入 / 註冊</button>
            )}
          </div>
        )}
      </header>

      <main className={`main${activePage === "terminal" ? " main-terminal" : ""}`}>
        {activePage === "search" && (
          <StockSearch onSelect={(t) => handleSelectStock(t)} />
        )}
        {activePage === "detail" && selectedTicker && (
          <StockDetail
            ticker={selectedTicker}
            onBack={goBack}
            onIndustry={handleSelectIndustry}
            watchlist={watchlist}
            onToggleWatch={toggleWatch}
          />
        )}
        {activePage === "industry" && selectedIndustry && (
          <IndustryStocks
            industry={selectedIndustry.name}
            excludeTicker={selectedIndustry.excludeTicker}
            onSelect={(t) => handleSelectStock(t)}
            onBack={goBack}
          />
        )}
        {activePage === "watchlist" && (
          <WatchList
            watchlist={watchlist}
            watchNotes={watchNotes}
            onRemove={toggleWatch}
            onSelect={(t) => handleSelectStock(t)}
            onUpdateNote={handleUpdateNote}
          />
        )}
        {activePage === "ranking" && (
          <TradeValueRanking onSelect={(t) => handleSelectStock(t)} />
        )}
        {activePage === "terminal" && (
          <TradingTerminal watchlist={watchlist} onToggleWatch={toggleWatch} />
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

      {showAuth && (
        <AuthModal
          onSuccess={(name) => { setUsername(name); setShowAuth(false); }}
          onClose={() => setShowAuth(false)}
        />
      )}

      {pendingWatch && (
        <WatchNoteModal
          ticker={pendingWatch}
          onConfirm={confirmAddWatch}
          onCancel={() => setPendingWatch(null)}
        />
      )}

      {/* 手機底部導覽列 */}
      <nav className="bottom-nav">
        <button
          className={activePage === "terminal" ? "active" : ""}
          onClick={() => setActivePage("terminal")}
        >
          <span className="bottom-nav-icon">📺</span>
          <span className="bottom-nav-label">看盤</span>
        </button>
        <button
          className={activePage === "ranking" ? "active" : ""}
          onClick={() => setActivePage("ranking")}
        >
          <span className="bottom-nav-icon">🏆</span>
          <span className="bottom-nav-label">排行</span>
        </button>
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
