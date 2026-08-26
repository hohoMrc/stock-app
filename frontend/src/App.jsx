import { useState, useEffect, useRef } from "react";
import StockSearch from "./components/StockSearch";
import StockDetail from "./components/StockDetail";
import StockScreener from "./components/StockScreener";
import IndustryStocks from "./components/IndustryStocks";
import WatchList from "./components/WatchList";
import AuthModal from "./components/AuthModal";
import WatchNoteModal from "./components/WatchNoteModal";
import TradeValueRanking from "./components/TradeValueRanking";
import TradingTerminal from "./components/TradingTerminal";
import AdminPage from "./components/AdminPage";
import FuturesPage from "./components/FuturesPage";
import PaperTrading from "./components/PaperTrading";
import NewsPage from "./components/NewsPage";
import AlertsPage from "./components/AlertsPage";
import DividendCalendar from "./components/DividendCalendar";
import WarrantLookup from "./components/WarrantLookup";
import ClaudeTrader from "./components/ClaudeTrader";
import SignalOverview from "./components/SignalOverview";
import MarketOverview from "./components/MarketOverview";
import {
  fetchWatchlist, addWatch, removeWatch, updateWatchNote,
  getWatchlistGroups, renameWatchlistGroup, updateWatchlistGroup,
} from "./api";

const ADMIN_USERNAME = "hoholin";
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

// 網址 <-> 畫面狀態互轉，讓切頁會反映在網址上，重新整理/上一頁/下一頁才不會跳掉。
// 也支援 ?ticker=XXXX&scan=YYYY 深層連結（從 TG 通知點進來，scan 決定預設顯示的均線）。
function parseStateFromLocation() {
  const params = new URLSearchParams(window.location.search);
  const ticker = params.get("ticker");
  const industry = params.get("industry");
  if (ticker) {
    return {
      activePage: "detail", selectedTicker: ticker,
      selectedTickerContext: params.get("scan") || null,
      selectedIndustry: null, paperPrefillTicker: null,
    };
  }
  if (industry) {
    return {
      activePage: "industry", selectedTicker: null, selectedTickerContext: null,
      selectedIndustry: {
        name: industry,
        excludeTicker: params.get("exclude") || null,
        useParent: params.get("parent") === "1",
      },
      paperPrefillTicker: null,
    };
  }
  if (params.get("page") === "paper" && params.get("paperTicker")) {
    return {
      activePage: "paper", selectedTicker: null, selectedTickerContext: null,
      selectedIndustry: null, paperPrefillTicker: params.get("paperTicker"),
    };
  }
  return {
    activePage: params.get("page") || "dashboard",
    selectedTicker: null, selectedTickerContext: null,
    selectedIndustry: null, paperPrefillTicker: null,
  };
}

function buildUrlFromState(s) {
  const params = new URLSearchParams();
  if (s.activePage === "detail" && s.selectedTicker) {
    params.set("ticker", s.selectedTicker);
    if (s.selectedTickerContext) params.set("scan", s.selectedTickerContext);
  } else if (s.activePage === "industry" && s.selectedIndustry) {
    params.set("page", "industry");
    params.set("industry", s.selectedIndustry.name);
    if (s.selectedIndustry.excludeTicker) params.set("exclude", s.selectedIndustry.excludeTicker);
    if (s.selectedIndustry.useParent) params.set("parent", "1");
  } else if (s.activePage === "paper" && s.paperPrefillTicker) {
    params.set("page", "paper");
    params.set("paperTicker", s.paperPrefillTicker);
  } else {
    params.set("page", s.activePage);
  }
  const qs = params.toString();
  return qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
}

export default function App() {
  const initialNavState = parseStateFromLocation();
  const [activePage, setActivePage] = useState(initialNavState.activePage);
  const [selectedTicker, setSelectedTicker] = useState(initialNavState.selectedTicker);
  const [selectedTickerContext, setSelectedTickerContext] = useState(initialNavState.selectedTickerContext);
  const [selectedIndustry, setSelectedIndustry] = useState(initialNavState.selectedIndustry);
  const [pageHistory, setPageHistory] = useState([]);
  const [paperPrefillTicker, setPaperPrefillTicker] = useState(initialNavState.paperPrefillTicker);

  // 每次切頁狀態變動就同步進網址（第一次進頁時只 replace，不佔用一筆歷史記錄）
  const isFirstNavSync = useRef(true);
  useEffect(() => {
    const navState = { activePage, selectedTicker, selectedTickerContext, selectedIndustry, paperPrefillTicker };
    const url = buildUrlFromState(navState);
    if (isFirstNavSync.current) {
      isFirstNavSync.current = false;
      window.history.replaceState(navState, "", url);
      return;
    }
    if (url !== window.location.pathname + window.location.search) {
      window.history.pushState(navState, "", url);
    }
  }, [activePage, selectedTicker, selectedTickerContext, selectedIndustry, paperPrefillTicker]);

  // 瀏覽器上一頁/下一頁：從 history state 還原（沒有 state 代表更早的紀錄，退回用網址自己解析）
  useEffect(() => {
    const onPopState = (e) => {
      const s = e.state || parseStateFromLocation();
      setActivePage(s.activePage);
      setSelectedTicker(s.selectedTicker ?? null);
      setSelectedTickerContext(s.selectedTickerContext ?? null);
      setSelectedIndustry(s.selectedIndustry ?? null);
      setPaperPrefillTicker(s.paperPrefillTicker ?? null);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // 篩選頁狀態提升，切頁後不遺失
  const [screenerFilters, setScreenerFilters] = useState(INIT_FILTERS);
  const [screenerResults, setScreenerResults] = useState([]);
  const [screenerSearched, setScreenerSearched] = useState(false);
  const [screenerAutoScan, setScreenerAutoScan] = useState(null);

  // 選股篩選點格子快速查看個股：右側滑出面板，不跳轉頁面、不影響篩選結果
  const [quickView, setQuickView] = useState(null); // { ticker, context } | null
  const openQuickView  = (ticker, context = null) => setQuickView({ ticker, context });
  const closeQuickView = () => setQuickView(null);

  // 帳號狀態
  const [username, setUsername] = useState(() => localStorage.getItem("username") || null);
  const [showAuth, setShowAuth] = useState(false);
  const [authExpired, setAuthExpired] = useState(false); // 是否是因為token過期才自動彈出登入視窗
  const [pendingWatch, setPendingWatch] = useState(null); // 等待填備注的 ticker
  const [menuOpen, setMenuOpen] = useState(false);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const moreMenuRef = useRef(null);

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    setUsername(null);
    setWatchlist([]);
    setWatchNotes({});
  };

  // token 過期/無效時（api.js 攔截器偵測到後端那句「Token 無效或已過期」），
  // 自動登出並彈出登入視窗，不用讓使用者自己意會那句錯誤訊息代表要重新登入。
  useEffect(() => {
    const onAuthExpired = () => {
      logout();
      setAuthExpired(true);
      setShowAuth(true);
    };
    window.addEventListener("auth:expired", onAuthExpired);
    return () => window.removeEventListener("auth:expired", onAuthExpired);
  }, []);

  // 自選清單（登入後從後端同步，否則用 localStorage）
  const [watchlist, setWatchlist] = useState(() => {
    try { return JSON.parse(localStorage.getItem("watchlist") || "[]"); }
    catch { return []; }
  });
  const [watchNotes, setWatchNotes] = useState({});
  const [watchAddedAt, setWatchAddedAt] = useState({});
  const [watchGroups, setWatchGroups] = useState([]);           // [{group_id, name}]，固定10組
  const [watchGroupByTicker, setWatchGroupByTicker] = useState({});

  useEffect(() => {
    if (username) {
      fetchWatchlist()
        .then((res) => {
          setWatchlist(res.data.tickers);
          setWatchNotes(res.data.notes || {});
          setWatchAddedAt(res.data.added_at || {});
          setWatchGroupByTicker(res.data.groups_by_ticker || {});
        })
        .catch(() => {});
      getWatchlistGroups()
        .then((res) => setWatchGroups(res.data.groups || []))
        .catch(() => {});
    } else {
      localStorage.setItem("watchlist", JSON.stringify(watchlist));
    }
  }, [username]);

  useEffect(() => {
    const handler = (e) => {
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target)) setMoreMenuOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

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

  const confirmAddWatch = async (ticker, note, groupId = 1) => {
    setPendingWatch(null);
    setWatchlist((prev) => [...prev, ticker]);
    setWatchAddedAt((prev) => ({ ...prev, [ticker]: Date.now() / 1000 }));
    setWatchGroupByTicker((prev) => ({ ...prev, [ticker]: groupId }));
    if (note) setWatchNotes((prev) => ({ ...prev, [ticker]: note }));
    try {
      await addWatch(ticker, groupId);
    } catch {
      // addWatch 失敗才 rollback
      setWatchlist((prev) => prev.filter((t) => t !== ticker));
      setWatchNotes((prev) => { const n = { ...prev }; delete n[ticker]; return n; });
      setWatchGroupByTicker((prev) => { const n = { ...prev }; delete n[ticker]; return n; });
      return;
    }
    // 備注儲存失敗不影響加入
    if (note) {
      try { await updateWatchNote(ticker, note); } catch { /* ignore */ }
    }
  };

  const renameWatchGroup = async (groupId, name) => {
    setWatchGroups((prev) => prev.map((g) => g.group_id === groupId ? { ...g, name } : g));
    try { await renameWatchlistGroup(groupId, name); } catch { /* ignore */ }
  };

  const moveWatchGroup = async (ticker, groupId) => {
    const prevGroupId = watchGroupByTicker[ticker];
    setWatchGroupByTicker((prev) => ({ ...prev, [ticker]: groupId }));
    try { await updateWatchlistGroup(ticker, groupId); } catch {
      setWatchGroupByTicker((prev) => ({ ...prev, [ticker]: prevGroupId }));
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

  const handleSelectStock = (ticker, context = null) => {
    setSelectedTicker(ticker);
    setSelectedTickerContext(context);
    setPageHistory((prev) => [...prev, activePage]);
    setActivePage("detail");
  };

  const handleSelectIndustry = (industry, fromTicker, useParent = false) => {
    setSelectedIndustry({ name: industry, excludeTicker: fromTicker, useParent });
    setPageHistory((prev) => [...prev, activePage]);
    setActivePage("industry");
  };

  // ticker 為 null 時代表從導覽列直接進入，不帶入任何股票
  const goToPaperTrading = (ticker = null) => {
    setPaperPrefillTicker(ticker);
    setActivePage("paper");
  };

  return (
    <div className="app">
      <header className="header">
        <h1 onClick={() => setActivePage("dashboard")}>台股分析工具</h1>

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
            className={activePage === "dashboard" ? "active" : ""}
            onClick={() => setActivePage("dashboard")}
          >
            大盤狀態
          </button>
          <button
            className={activePage === "terminal" ? "active" : ""}
            onClick={() => setActivePage("terminal")}
          >
            看盤
          </button>
          <button
            className={activePage === "futures" ? "active" : ""}
            onClick={() => setActivePage("futures")}
          >
            台指期
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
          <button
            className={activePage === "paper" ? "active" : ""}
            onClick={() => goToPaperTrading()}
          >
            模擬下單
          </button>
          <div className="nav-more-wrap" ref={moreMenuRef}>
            <button
              className={`nav-more-btn ${["alerts", "dividends", "news", "warrant-lookup", "claude-trader", "signal-overview"].includes(activePage) ? "active" : ""}`}
              onClick={() => setMoreMenuOpen((v) => !v)}
            >
              更多 ▾
            </button>
            {moreMenuOpen && (
              <div className="nav-more-menu">
                <button
                  className={activePage === "alerts" ? "active" : ""}
                  onClick={() => { setActivePage("alerts"); setMoreMenuOpen(false); }}
                >
                  提醒
                </button>
                <button
                  className={activePage === "dividends" ? "active" : ""}
                  onClick={() => { setActivePage("dividends"); setMoreMenuOpen(false); }}
                >
                  除權息
                </button>
                <button
                  className={activePage === "news" ? "active" : ""}
                  onClick={() => { setActivePage("news"); setMoreMenuOpen(false); }}
                >
                  新聞
                </button>
                <button
                  className={activePage === "warrant-lookup" ? "active" : ""}
                  onClick={() => { setActivePage("warrant-lookup"); setMoreMenuOpen(false); }}
                >
                  權證查詢
                </button>
                <button
                  className={activePage === "claude-trader" ? "active" : ""}
                  onClick={() => { setActivePage("claude-trader"); setMoreMenuOpen(false); }}
                >
                  Claude自動交易
                </button>
                <button
                  className={activePage === "signal-overview" ? "active" : ""}
                  onClick={() => { setActivePage("signal-overview"); setMoreMenuOpen(false); }}
                >
                  訊號績效總覽
                </button>
              </div>
            )}
          </div>
          {username === ADMIN_USERNAME && (
            <button
              className={activePage === "admin" ? "active" : ""}
              onClick={() => setActivePage("admin")}
            >
              管理
            </button>
          )}
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
              className={activePage === "dashboard" ? "active" : ""}
              onClick={() => setActivePage("dashboard")}
            >大盤狀態</button>
            <button
              className={["search", "detail", "industry"].includes(activePage) ? "active" : ""}
              onClick={() => setActivePage("search")}
            >個股查詢</button>
            <button
              className={activePage === "screener" ? "active" : ""}
              onClick={() => setActivePage("screener")}
            >選股篩選</button>
            <button
              className={activePage === "news" ? "active" : ""}
              onClick={() => setActivePage("news")}
            >新聞</button>
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
            <button
              className={activePage === "futures" ? "active" : ""}
              onClick={() => setActivePage("futures")}
            >台指期</button>
            <button
              className={activePage === "paper" ? "active" : ""}
              onClick={() => goToPaperTrading()}
            >模擬下單</button>
            <button
              className={activePage === "alerts" ? "active" : ""}
              onClick={() => setActivePage("alerts")}
            >提醒</button>
            <button
              className={activePage === "dividends" ? "active" : ""}
              onClick={() => setActivePage("dividends")}
            >除權息</button>
            <button
              className={activePage === "warrant-lookup" ? "active" : ""}
              onClick={() => setActivePage("warrant-lookup")}
            >權證查詢</button>
            <button
              className={activePage === "claude-trader" ? "active" : ""}
              onClick={() => setActivePage("claude-trader")}
            >Claude自動交易</button>
            <button
              className={activePage === "signal-overview" ? "active" : ""}
              onClick={() => setActivePage("signal-overview")}
            >訊號績效總覽</button>
            {username === ADMIN_USERNAME && (
              <button
                className={activePage === "admin" ? "active" : ""}
                onClick={() => setActivePage("admin")}
              >管理</button>
            )}
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
        {activePage === "dashboard" && (
          <MarketOverview
            onSelect={(t) => handleSelectStock(t)}
            onSelectIndustry={(ind) => handleSelectIndustry(ind, null, true)}
            onNavigate={(p, scan) => {
              if (scan) setScreenerAutoScan(scan);
              setActivePage(p);
            }}
          />
        )}
        {activePage === "search" && (
          <StockSearch onSelect={(t) => handleSelectStock(t)} />
        )}
        {activePage === "detail" && selectedTicker && (
          <StockDetail
            ticker={selectedTicker}
            scanContext={selectedTickerContext}
            onBack={goBack}
            onIndustry={handleSelectIndustry}
            watchlist={watchlist}
            onToggleWatch={toggleWatch}
            onPaperTrade={goToPaperTrading}
            username={username}
            onRequireLogin={() => setShowAuth(true)}
          />
        )}
        {activePage === "industry" && selectedIndustry && (
          <IndustryStocks
            industry={selectedIndustry.name}
            excludeTicker={selectedIndustry.excludeTicker}
            useParent={selectedIndustry.useParent}
            onSelect={(t) => handleSelectStock(t)}
            onBack={goBack}
          />
        )}
        {activePage === "watchlist" && (
          <WatchList
            watchlist={watchlist}
            watchNotes={watchNotes}
            watchAddedAt={watchAddedAt}
            watchGroups={watchGroups}
            watchGroupByTicker={watchGroupByTicker}
            onRemove={toggleWatch}
            onSelect={(t) => handleSelectStock(t)}
            onUpdateNote={handleUpdateNote}
            onRenameGroup={renameWatchGroup}
            onMoveGroup={moveWatchGroup}
          />
        )}
        {activePage === "ranking" && (
          <TradeValueRanking
            onSelect={(t) => handleSelectStock(t)}
            onSelectIndustry={(ind) => handleSelectIndustry(ind, null, true)}
          />
        )}
        {activePage === "terminal" && (
          <TradingTerminal watchlist={watchlist} onToggleWatch={toggleWatch} username={username} onSelect={(t) => handleSelectStock(t)} />
        )}
        {activePage === "futures" && (
          <FuturesPage
            username={username}
            onRequireLogin={() => setShowAuth(true)}
            onNavigate={(p) => setActivePage(p)}
          />
        )}
        {activePage === "news" && <NewsPage onSelectStock={handleSelectStock} />}
        {activePage === "alerts" && (
          <AlertsPage
            username={username}
            onRequireLogin={() => setShowAuth(true)}
            onSelect={(t) => handleSelectStock(t)}
          />
        )}
        {activePage === "dividends" && (
          <DividendCalendar onSelect={(t) => handleSelectStock(t)} />
        )}
        {activePage === "warrant-lookup" && (
          <WarrantLookup onSelect={(t) => handleSelectStock(t)} />
        )}
        {activePage === "claude-trader" && <ClaudeTrader onSelect={(t) => handleSelectStock(t)} />}
        {activePage === "signal-overview" && <SignalOverview />}
        {activePage === "paper" && (
          <PaperTrading
            username={username}
            onRequireLogin={() => setShowAuth(true)}
            prefillTicker={paperPrefillTicker}
            onSelectStock={(t) => handleSelectStock(t)}
          />
        )}
        {activePage === "admin" && username === ADMIN_USERNAME && (
          <AdminPage />
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
            onSelect={openQuickView}
            autoScan={screenerAutoScan}
            onAutoScanHandled={() => setScreenerAutoScan(null)}
          />
        </div>
      </main>

      {quickView && (
        <div className="quickview-overlay" onClick={closeQuickView}>
          <div className="quickview-drawer" onClick={(e) => e.stopPropagation()}>
            <button className="quickview-close" onClick={closeQuickView} title="關閉">✕</button>
            <StockDetail
              ticker={quickView.ticker}
              scanContext={quickView.context}
              onBack={closeQuickView}
              onIndustry={(industry, fromTicker, useParent) => {
                closeQuickView();
                handleSelectIndustry(industry, fromTicker, useParent);
              }}
              watchlist={watchlist}
              onToggleWatch={toggleWatch}
              onPaperTrade={(t) => { closeQuickView(); goToPaperTrading(t); }}
              username={username}
              onRequireLogin={() => setShowAuth(true)}
            />
          </div>
        </div>
      )}

      {showAuth && (
        <AuthModal
          message={authExpired ? "登入已過期，請重新登入" : null}
          onSuccess={(name) => { setUsername(name); setShowAuth(false); setAuthExpired(false); }}
          onClose={() => { setShowAuth(false); setAuthExpired(false); }}
        />
      )}

      {pendingWatch && (
        <WatchNoteModal
          ticker={pendingWatch}
          groups={watchGroups}
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
        <button
          className={activePage === "paper" ? "active" : ""}
          onClick={() => goToPaperTrading()}
        >
          <span className="bottom-nav-icon">💰</span>
          <span className="bottom-nav-label">下單</span>
        </button>
      </nav>
    </div>
  );
}
