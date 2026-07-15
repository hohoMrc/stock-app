import { useState, useEffect, useRef } from "react";
import CandlestickChart from "./CandlestickChart";
import { getTradeValueRanking, getTurnoverRanking, getHistory, getOrderbook, getTrades, getPaperPositions } from "../api";

const INTERVAL_CONFIG = {
  "1m":  { fetchPeriod: "5d",  defaultPeriod: "1d",  periods: ["1d", "3d", "5d"] },
  "5m":  { fetchPeriod: "1mo", defaultPeriod: "5d",  periods: ["3d", "5d", "1mo"] },
  "15m": { fetchPeriod: "1mo", defaultPeriod: "5d",  periods: ["3d", "5d", "1mo"] },
  "60m": { fetchPeriod: "3mo", defaultPeriod: "5d",  periods: ["5d", "1mo", "3mo"] },
  "1d":  { fetchPeriod: "1y",  defaultPeriod: "3mo", periods: ["1mo", "3mo", "6mo", "1y"] },
  "1wk": { fetchPeriod: "2y",  defaultPeriod: "1y",  periods: ["3mo", "6mo", "1y", "2y"] },
  "1mo": { fetchPeriod: "5y",  defaultPeriod: "2y",  periods: ["1y", "2y", "5y"] },
};

const PERIOD_LABELS = {
  "1d": "1日", "3d": "3日", "5d": "5天",
  "1mo": "1月", "3mo": "3月", "6mo": "6月",
  "1y": "1年", "2y": "2年", "5y": "5年",
};

const INTERVAL_LABELS = {
  "1m": "1分", "5m": "5分", "15m": "15分",
  "60m": "60分", "1d": "日K", "1wk": "週K", "1mo": "月K",
};

export default function TradingTerminal({ watchlist = [], onToggleWatch, username }) {
  const [activeTab, setActiveTab]       = useState("value");
  const [listData, setListData]         = useState({ value: [], turnover: [] });
  const [listLoading, setListLoading]   = useState({ value: false, turnover: false });
  const [listUpdatedAt, setListUpdatedAt] = useState({ value: null, turnover: null });
  const loaded = useRef({ value: false, turnover: false });

  const [holdings, setHoldings]               = useState([]);
  const [holdingsLoading, setHoldingsLoading] = useState(false);
  const holdingsLoaded = useRef(false);

  const [selected, setSelected]         = useState(null); // { ticker, name, close, change, change_pct }
  const [chartData, setChartData]       = useState([]);
  const [chartInterval, setChartInterval] = useState("1d");
  const [chartPeriod, setChartPeriod]   = useState("3mo");
  const [chartLoading, setChartLoading] = useState(false);
  const [orderbook, setOrderbook]       = useState({ best_bids: [], best_asks: [] });
  const [trades, setTrades]             = useState([]);
  const [obLoading, setObLoading]       = useState(false);

  // 手機版：顯示哪個面板 ("list" | "chart")
  const [mobileView, setMobileView] = useState("list");

  // ── 可拖曳分隔線（控制右側寬度，左側 flex:1 自然伸縮）────────────────
  const [rightWidth, setRightWidth] = useState(560);
  const wrapRef      = useRef(null);
  const rightRef     = useRef(null);
  const isDragging   = useRef(false);
  const dragStartX   = useRef(0);

  const dragStartRW  = useRef(560);

  const onDividerDown = (e) => {
    isDragging.current  = true;
    dragStartX.current  = e.clientX;
    dragStartRW.current = rightRef.current?.getBoundingClientRect().width ?? 560;
    document.body.style.cursor     = "col-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();
  };

  useEffect(() => {
    const onMove = (e) => {
      if (!isDragging.current || !wrapRef.current) return;
      const dx    = e.clientX - dragStartX.current;
      const total = wrapRef.current.getBoundingClientRect().width;
      // 向右拖 → 右側縮小；向左拖 → 右側增大
      const newRW = Math.max(300, Math.min(total - 260, dragStartRW.current - dx));
      setRightWidth(newRW);
    };
    const onUp = () => {
      if (!isDragging.current) return;
      isDragging.current             = false;
      document.body.style.cursor     = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup",   onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup",   onUp);
    };
  }, []);


  // ── 排行清單 ──────────────────────────────────────────────────────────
  const loadList = async (tab) => {
    setListLoading((p) => ({ ...p, [tab]: true }));
    try {
      const res = tab === "value"
        ? await getTradeValueRanking(50)
        : await getTurnoverRanking(50);
      setListData((p) => ({ ...p, [tab]: res.data.stocks }));
      setListUpdatedAt((p) => ({
        ...p,
        [tab]: new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" }),
      }));
      loaded.current[tab] = true;
    } catch { /* ignore */ }
    finally { setListLoading((p) => ({ ...p, [tab]: false })); }
  };

  useEffect(() => { loadList("value"); }, []);
  useEffect(() => {
    if (!loaded.current[activeTab] && activeTab !== "watch" && activeTab !== "holdings") loadList(activeTab);
  }, [activeTab]);

  // ── 持股（模擬下單）──────────────────────────────────────────────────
  const loadHoldings = async () => {
    if (!username) return;
    setHoldingsLoading(true);
    try {
      const res = await getPaperPositions();
      setHoldings(res.data.positions);
      holdingsLoaded.current = true;
    } catch { /* ignore */ }
    finally { setHoldingsLoading(false); }
  };

  useEffect(() => {
    if (activeTab === "holdings" && username && !holdingsLoaded.current) loadHoldings();
  }, [activeTab, username]);

  // ── K 線資料 ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!selected) return;
    const cfg = INTERVAL_CONFIG[chartInterval];
    setChartPeriod(cfg.defaultPeriod);
    setChartLoading(true);
    setChartData([]);
    getHistory(selected.ticker, cfg.fetchPeriod, chartInterval)
      .then((res) => setChartData(res.data.data))
      .catch(() => {})
      .finally(() => setChartLoading(false));
  }, [selected?.ticker, chartInterval]);

  // ── 委買委賣 + 成交明細（10 秒自動刷新）────────────────────────────
  useEffect(() => {
    if (!selected) return;
    let alive = true;
    const fetchAll = () => {
      setObLoading(true);
      Promise.all([
        getOrderbook(selected.ticker),
        getTrades(selected.ticker, 20),
      ])
        .then(([obRes, trRes]) => {
          if (!alive) return;
          setOrderbook(obRes.data);
          setTrades(trRes.data.trades || []);
        })
        .catch(() => {})
        .finally(() => { if (alive) setObLoading(false); });
    };
    fetchAll();
    const timer = setInterval(fetchAll, 10000);
    return () => { alive = false; clearInterval(timer); };
  }, [selected?.ticker]);

  const handleSelect = (s) => {
    setSelected(s);
    setMobileView("chart");
  };

  const stocks = activeTab === "watch"
    ? watchlist.map((t) => ({ ticker: t, name: "" }))
    : activeTab === "holdings"
    ? holdings.map((p) => ({
        ticker: p.ticker, name: p.name,
        close: p.price, change: p.change, change_pct: p.change_pct,
        trade_volume_zhang: p.volume_zhang,
      }))
    : listData[activeTab];

  return (
    <div className="terminal-wrap" ref={wrapRef}>
      {/* ── 手機：頂部切換列 ── */}
      <div className="terminal-mobile-switcher">
        <button
          className={mobileView === "list" ? "active" : ""}
          onClick={() => setMobileView("list")}
        >
          名單
        </button>
        <button
          className={mobileView === "chart" ? "active" : ""}
          onClick={() => setMobileView("chart")}
          disabled={!selected}
        >
          {selected ? `${selected.ticker} 圖表` : "圖表"}
        </button>
      </div>

      {/* ── 左側：股票清單 ── */}
      <div className={`terminal-left ${mobileView !== "list" ? "terminal-hide-mobile" : ""}`}>
        <div className="terminal-list-tabs">
          {[
            { key: "value",    label: "成交值" },
            { key: "turnover", label: "週轉率" },
            { key: "watch",    label: "自選" },
            { key: "holdings", label: "持股" },
          ].map(({ key, label }) => (
            <button
              key={key}
              className={activeTab === key ? "active" : ""}
              onClick={() => setActiveTab(key)}
            >
              {label}
            </button>
          ))}
          <button
            className="tl-refresh"
            onClick={() => {
              if (activeTab === "holdings") loadHoldings();
              else if (activeTab !== "watch") loadList(activeTab);
            }}
            title="重新整理"
          >
            ↻
          </button>
        </div>
        {listUpdatedAt[activeTab] && (
          <div className="tl-updated">更新 {listUpdatedAt[activeTab]}</div>
        )}
        <div className="tl-table-wrap">
          {(activeTab === "holdings" ? holdingsLoading : listLoading[activeTab]) && (
            <div className="tl-loading">載入中...</div>
          )}
          <table className="tl-table">
            <thead>
              <tr>
                <th className="th-left">代號</th>
                <th className="th-left">名稱</th>
                <th>成交價</th>
                <th>漲跌幅</th>
                <th>漲跌</th>
                <th>成交量▼</th>
                <th>委買</th>
                <th>委賣</th>
                <th>單量</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((s) => {
                const up      = s.change > 0;
                const down    = s.change < 0;
                const sign    = up ? "+" : "";
                const limitUp = s.is_limit_up;
                const limitDown = s.is_limit_down;
                const vol     = s.trade_volume_zhang;
                const isBuy   = s.last_trade_dir === "buy";
                const isSell  = s.last_trade_dir === "sell";
                const dir     = up ? "up" : down ? "down" : "";
                return (
                  <tr
                    key={s.ticker}
                    className={selected?.ticker === s.ticker ? "tl-selected" : ""}
                    onClick={() => handleSelect(s)}
                  >
                    <td className="tl-col-code">
                      <span
                        className={`tl-star ${watchlist.includes(s.ticker) ? "tl-star--on" : ""}`}
                        onClick={(e) => { e.stopPropagation(); onToggleWatch(s.ticker); }}
                        title={watchlist.includes(s.ticker) ? "移除自選" : "加入自選"}
                      >
                        {watchlist.includes(s.ticker) ? "★" : "☆"}
                      </span>
                      {s.ticker}
                    </td>
                    <td className="tl-col-name">{s.name || s.ticker}</td>
                    <td className="tl-col-price">
                      <span className={`tl-price ${limitUp ? "limit-up" : limitDown ? "limit-down" : dir}`}>
                        {s.close ?? "—"}
                      </span>
                    </td>
                    <td className={`tl-num ${dir}`}>
                      {s.change_pct != null ? `${sign}${s.change_pct}%` : "—"}
                    </td>
                    <td className={`tl-num ${dir}`}>
                      {s.change != null ? `${sign}${s.change}` : "—"}
                    </td>
                    <td className="tl-num">{vol != null ? vol.toLocaleString() : "—"}</td>
                    <td className={`tl-num ${dir}`}>{s.best_bid ?? "—"}</td>
                    <td className={`tl-num ${dir}`}>{s.best_ask ?? "—"}</td>
                    <td className="tl-col-last">
                      {s.last_size_zhang != null ? (
                        <span className={`tl-last-size ${isBuy ? "buy" : isSell ? "sell" : ""}`}>
                          {s.last_size_zhang.toLocaleString()}
                        </span>
                      ) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {activeTab === "holdings" && !username && (
            <div className="tl-empty">請先登入才能查看模擬下單持股</div>
          )}
          {activeTab === "holdings" && username && !holdingsLoading && stocks.length === 0 && (
            <div className="tl-empty">尚無持股</div>
          )}
          {activeTab !== "holdings" && !listLoading[activeTab] && stocks.length === 0 && (
            <div className="tl-empty">暫無資料</div>
          )}
        </div>

        {/* ── 委買委賣 + 成交明細（選股後顯示）── */}
        {selected && (
          <div className="terminal-orderbook">
            <div className="ob-panels">
              <OrderBook data={orderbook} loading={obLoading} />
              <TradeList trades={trades} />
            </div>
          </div>
        )}
      </div>

      {/* ── 可拖曳分隔線 ── */}
      <div className="terminal-divider terminal-hide-mobile" onMouseDown={onDividerDown} />

      {/* ── 右側：圖表 ── */}
      <div
        ref={rightRef}
        className={`terminal-right ${mobileView !== "chart" ? "terminal-hide-mobile" : ""}`}
        style={{ width: rightWidth, minWidth: 0 }}
      >
        {selected ? (
          <>
            {/* 圖表控制列：改下拉選單節省空間 */}
            <div className="terminal-chart-controls">
              <select
                className="tcc-select"
                value={chartInterval}
                onChange={(e) => setChartInterval(e.target.value)}
              >
                {Object.entries(INTERVAL_LABELS).map(([iv, label]) => (
                  <option key={iv} value={iv}>{label}</option>
                ))}
              </select>
              <select
                className="tcc-select"
                value={chartPeriod}
                onChange={(e) => setChartPeriod(e.target.value)}
              >
                {INTERVAL_CONFIG[chartInterval].periods.map((p) => (
                  <option key={p} value={p}>{PERIOD_LABELS[p]}</option>
                ))}
              </select>
            </div>

            {/* K 線圖 */}
            <div className="terminal-chart-area">
              {chartLoading ? (
                <div className="terminal-loading">載入圖表...</div>
              ) : chartData.length > 0 ? (
                <CandlestickChart
                  data={chartData}
                  period={chartPeriod}
                  interval={chartInterval}
                  showMACD={false}
                />
              ) : (
                <div className="terminal-loading">無圖表資料</div>
              )}
            </div>

</>
        ) : (
          <div className="terminal-empty">← 從左側點選股票查看圖表</div>
        )}
      </div>
    </div>
  );
}

function OrderBook({ data, loading }) {
  const bids = (data.best_bids || []).slice(0, 5);
  const asks = (data.best_asks || []).slice(0, 5);
  const isRealtime = data.is_realtime;

  if (!loading && bids.length === 0 && asks.length === 0) {
    return (
      <div className="ob-empty">
        盤中交易時段將自動顯示即時五檔，收盤後顯示最後快照
      </div>
    );
  }

  const totalBid = bids.reduce((s, b) => s + (b.size || 0), 0);
  const totalAsk = asks.reduce((s, a) => s + (a.size || 0), 0);
  const total    = totalBid + totalAsk;
  const bidPct   = total > 0 ? Math.round((totalBid / total) * 100) : 0;
  const askPct   = 100 - bidPct;
  // 價格 0 代表沒有限價（市價委託），直接顯示目前市價
  const displayPrice = (price) => (price === 0 ? (data.close ?? price) : price);

  return (
    <div className="ob-wrap">
      <div className="ob-header-row">
        <span className="ob-title">委買委賣五檔</span>
        {!loading && bids.length > 0 && (
          <span className={`ob-data-tag ${isRealtime ? "ob-tag-live" : "ob-tag-snapshot"}`}>
            {isRealtime ? "即時" : "收盤快照"}
          </span>
        )}
        {loading && <span className="ob-refreshing">刷新中</span>}
      </div>

      <div className="ob-grid">
        {/* 委買（綠）：由高到低排列 */}
        <div className="ob-col ob-bid-col">
          <div className="ob-col-header">
            <span>委買價</span>
            <span>張數</span>
          </div>
          {bids.map((b, i) => (
            <div key={i} className="ob-row">
              <span className="ob-price up">{displayPrice(b.price)}</span>
              <span className="ob-qty">{b.size}</span>
              <div className="ob-bar-wrap">
                <div
                  className="ob-bar ob-bar-bid"
                  style={{ width: totalBid > 0 ? `${((b.size / totalBid) * 100).toFixed(0)}%` : "0%" }}
                />
              </div>
            </div>
          ))}
        </div>

        {/* 委賣（紅）：由高到低排列 */}
        <div className="ob-col ob-ask-col">
          <div className="ob-col-header">
            <span>委賣價</span>
            <span>張數</span>
          </div>
          {[...asks].reverse().map((a, i) => (
            <div key={i} className="ob-row">
              <span className="ob-price down">{displayPrice(a.price)}</span>
              <span className="ob-qty">{a.size}</span>
              <div className="ob-bar-wrap">
                <div
                  className="ob-bar ob-bar-ask"
                  style={{ width: totalAsk > 0 ? `${((a.size / totalAsk) * 100).toFixed(0)}%` : "0%" }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 買賣壓力比 */}
      {total > 0 && (
        <div className="ob-pressure">
          <span className="ob-pct up">{bidPct}% 買</span>
          <div className="ob-pressure-bar">
            <div className="ob-pressure-bid" style={{ width: `${bidPct}%` }} />
            <div className="ob-pressure-ask" style={{ width: `${askPct}%` }} />
          </div>
          <span className="ob-pct down">{askPct}% 賣</span>
        </div>
      )}
    </div>
  );
}

function TradeList({ trades }) {
  if (!trades || trades.length === 0) return null;

  return (
    <div className="tradelist-wrap">
      <div className="ob-title" style={{ marginBottom: 6 }}>成交明細</div>
      <div className="tradelist-header">
        <span>時間</span>
        <span>成交價</span>
        <span>張數</span>
        <span>方向</span>
      </div>
      <div className="tradelist-scroll">
        {trades.map((t, i) => {
          const isBuy  = t.price != null && t.ask != null && t.price >= t.ask;
          const isSell = t.price != null && t.bid != null && t.price <= t.bid;
          return (
            <div key={i} className={`tradelist-row ${isBuy ? "buy" : isSell ? "sell" : ""}`}>
              <span className="tl-time">{t.time ?? "—"}</span>
              <span className={`tl-tp ${isBuy ? "up" : isSell ? "down" : ""}`}>{t.price ?? "—"}</span>
              <span className="tl-sz">{t.size ?? "—"}</span>
              <span className={`tl-dir ${isBuy ? "up" : isSell ? "down" : ""}`}>
                {isBuy ? "買" : isSell ? "賣" : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
