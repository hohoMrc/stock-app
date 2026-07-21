import { useState, useEffect, useRef, useMemo } from "react";
import { LineChart, Line, BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from "recharts";
import CandlestickChart from "./CandlestickChart";
import { getTradeValueRanking, getTurnoverRanking, getHistory, getOrderbook, getTrades, getPaperPositions, getWatchlistQuotes, getIntradayChart } from "../api";
import { isTradingHours } from "../marketHours";

const WS_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  .replace(/^http/, "ws");

// 分時圖時間軸固定畫到收盤（09:00~13:30），不要隨資料進來越畫越長，
// 還沒到的時間點補空值，recharts 遇到 null 自然留白不畫。
function padIntradayToFullDay(intradayData) {
  const map = new Map(intradayData.map((d) => [d.time, d]));
  const result = [];
  for (let mins = 9 * 60; mins <= 13 * 60 + 30; mins++) {
    const time = `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
    result.push(map.get(time) || { time, price: null, average: null, volume: null });
  }
  return result;
}

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
  const [listWsKey, setListWsKey] = useState(0);   // 遞增觸發排行清單 WebSocket 重連
  const listWsRef = useRef(null);

  const [holdings, setHoldings]               = useState([]);
  const [holdingsLoading, setHoldingsLoading] = useState(false);
  const holdingsLoaded = useRef(false);

  const [watchQuotes, setWatchQuotes]   = useState([]);
  const [watchLoading, setWatchLoading] = useState(false);

  const [selected, setSelected]         = useState(null); // { ticker, name, close, change, change_pct }
  const [chartData, setChartData]       = useState([]);
  const [chartInterval, setChartInterval] = useState("1d");
  const [chartPeriod, setChartPeriod]   = useState("3mo");
  const [chartLoading, setChartLoading] = useState(false);
  const [orderbook, setOrderbook]       = useState({ best_bids: [], best_asks: [] });
  const [trades, setTrades]             = useState([]);
  const [obLoading, setObLoading]       = useState(false);
  const [wsKey, setWsKey]               = useState(0);   // 遞增觸發 WebSocket 重連
  const wsRef                           = useRef(null);
  const [obTab, setObTab]               = useState("book"); // "book" | "trades"
  const [intradayData, setIntradayData] = useState([]);
  const intradayPollRef                 = useRef(null);

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

  // 首次進來右側是空的，預設選成交值第一名，避免畫面一開始半邊空白
  useEffect(() => {
    if (!selected && listData.value.length > 0) {
      handleSelect(listData.value[0]);
    }
  }, [listData.value]);

  // ── 排行清單 WebSocket 即時更新（成交值/成交量/持股分頁，依目前清單的股票代號訂閱）──
  const mergeWsRow = (row, data) => {
    if (data.channel === "books") {
      const bid = data.bids?.[0] ? Math.round(data.bids[0].price * 100) / 100 : row.best_bid;
      const ask = data.asks?.[0] ? Math.round(data.asks[0].price * 100) / 100 : row.best_ask;
      return { ...row, best_bid: bid, best_ask: ask };
    }
    if (data.channel === "trades") {
      const ref = row.close != null && row.change != null ? row.close - row.change : null;
      let change = row.change, changePct = row.change_pct;
      if (ref != null && data.price != null) {
        change = Math.round((data.price - ref) * 100) / 100;
        changePct = ref ? Math.round((change / ref) * 10000) / 100 : changePct;
      }
      const isBuy  = data.price != null && data.ask != null && data.price >= data.ask;
      const isSell = data.price != null && data.bid != null && data.price <= data.bid;
      return {
        ...row,
        close: data.price ?? row.close,
        change,
        change_pct: changePct,
        trade_volume_zhang: data.volume ?? row.trade_volume_zhang,
        last_size_zhang: data.size ?? row.last_size_zhang,
        last_trade_dir: isBuy ? "buy" : isSell ? "sell" : row.last_trade_dir,
      };
    }
    return row;
  };

  const listTickers = (activeTab === "value" || activeTab === "turnover")
    ? (listData[activeTab] || []).map((s) => s.ticker).join(",")
    : activeTab === "holdings"
    ? holdings.map((p) => p.ticker).join(",")
    : activeTab === "watch"
    ? watchlist.join(",")
    : "";

  useEffect(() => {
    if (!listTickers) return;
    if (listWsRef.current) { listWsRef.current.close(); listWsRef.current = null; }
    const tabKey = activeTab;
    const ws = new WebSocket(`${WS_BASE}/ws/stocks?symbols=${encodeURIComponent(listTickers)}`);
    listWsRef.current = ws;
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.event === "keepalive" || !data.symbol) return;
        if (tabKey === "holdings" || tabKey === "watch") {
          const setter = tabKey === "holdings" ? setHoldings : setWatchQuotes;
          setter((prev) => {
            const idx = prev.findIndex((r) => r.ticker === data.symbol);
            if (idx === -1) return prev;
            const updated = mergeWsRow(prev[idx], data);
            if (updated === prev[idx]) return prev;
            const next = [...prev];
            next[idx] = updated;
            return next;
          });
          return;
        }
        setListData((prev) => {
          const rows = prev[tabKey];
          if (!rows) return prev;
          const idx = rows.findIndex((r) => r.ticker === data.symbol);
          if (idx === -1) return prev;
          const updated = mergeWsRow(rows[idx], data);
          if (updated === rows[idx]) return prev;
          const newRows = [...rows];
          newRows[idx] = updated;
          return { ...prev, [tabKey]: newRows };
        });
      } catch (_) {}
    };
    ws.onerror = () => {};
    ws.onclose = () => {
      // 斷線後 3 秒自動重連
      setTimeout(() => setListWsKey((k) => k + 1), 3000);
    };
    return () => {
      ws.onclose = null;   // 清掉 onclose 避免 cleanup 時觸發重連
      ws.close();
      listWsRef.current = null;
    };
  }, [listTickers, activeTab, listWsKey]);

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

  // ── 自選股：股名/成交價/委買委賣（切到分頁或自選清單變動時重新抓取，WS 接手後續即時更新）──
  const watchTickers = watchlist.join(",");
  useEffect(() => {
    if (activeTab !== "watch") return;
    if (!watchTickers) { setWatchQuotes([]); return; }
    let alive = true;
    setWatchLoading(true);
    getWatchlistQuotes(watchlist)
      .then((res) => { if (alive) setWatchQuotes(res.data.stocks); })
      .catch(() => {})
      .finally(() => { if (alive) setWatchLoading(false); });
    return () => { alive = false; };
  }, [activeTab, watchTickers]);

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

  // ── 當日分時走勢圖（交易時段內每15秒刷新）────────────────────────
  useEffect(() => {
    if (!selected) { setIntradayData([]); return; }
    let alive = true;
    const load = () =>
      getIntradayChart(selected.ticker)
        .then((res) => { if (alive) setIntradayData(res.data.points); })
        .catch(() => { if (alive) setIntradayData([]); });
    load();
    clearInterval(intradayPollRef.current);
    intradayPollRef.current = setInterval(() => { if (isTradingHours()) load(); }, 15000);
    return () => { alive = false; clearInterval(intradayPollRef.current); };
  }, [selected?.ticker]);

  // ── WebSocket 即時委買委賣 + 成交明細（REST 輪詢仍保留作保底）────────
  useEffect(() => {
    if (!selected) return;
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    const ws = new WebSocket(`${WS_BASE}/ws/stock?symbol=${selected.ticker}`);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.event === "keepalive") return;
        if (data.channel === "books") {
          const norm = (arr) => (arr || []).map((x) => ({
            price: Math.round(x.price * 100) / 100,
            size: x.size,
          }));
          setOrderbook((prev) => ({
            ...prev,
            best_bids: norm(data.bids),
            best_asks: norm(data.asks),
            is_realtime: true,
          }));
        } else if (data.channel === "trades") {
          const timeStr = data.time
            ? new Date(data.time / 1000).toLocaleTimeString("zh-TW", { hour12: false, timeZone: "Asia/Taipei" })
            : null;
          const trade = { time: timeStr, price: data.price, size: data.size, bid: data.bid, ask: data.ask };
          setTrades((prev) => [trade, ...prev].slice(0, 20));
        }
      } catch (_) {}
    };
    ws.onerror = () => {};
    ws.onclose = () => {
      // 斷線後 3 秒自動重連
      setTimeout(() => setWsKey((k) => k + 1), 3000);
    };
    return () => {
      ws.onclose = null;   // 清掉 onclose 避免 cleanup 時觸發重連
      ws.close();
      wsRef.current = null;
    };
  }, [selected?.ticker, wsKey]);

  const handleSelect = (s) => {
    setSelected(s);
    setMobileView("chart");
  };

  const stocks = activeTab === "watch"
    ? watchQuotes
    : activeTab === "holdings"
    ? holdings.map((p) => ({
        ticker: p.ticker, name: p.name,
        close: p.close ?? p.price, change: p.change, change_pct: p.change_pct,
        trade_volume_zhang: p.trade_volume_zhang ?? p.volume_zhang,
        best_bid: p.best_bid, best_ask: p.best_ask,
        last_size_zhang: p.last_size_zhang, last_trade_dir: p.last_trade_dir,
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
          {(activeTab === "holdings" ? holdingsLoading : activeTab === "watch" ? watchLoading : listLoading[activeTab]) && (
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
                    <td className={`tl-num ${dir}`}>{s.best_bid === 0 ? "市價" : s.best_bid ?? "—"}</td>
                    <td className={`tl-num ${dir}`}>{s.best_ask === 0 ? "市價" : s.best_ask ?? "—"}</td>
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
          {activeTab === "watch" && !watchLoading && stocks.length === 0 && (
            <div className="tl-empty">尚未加入自選股</div>
          )}
          {activeTab !== "holdings" && activeTab !== "watch" && !listLoading[activeTab] && stocks.length === 0 && (
            <div className="tl-empty">暫無資料</div>
          )}
        </div>

        {/* ── 委買委賣/成交明細（分頁切換）+ 當日走勢（選股後顯示）── */}
        {selected && (
          <div className="terminal-orderbook">
            <div className="ob-panels">
              <div className="ob-left-col">
                <div className="terminal-list-tabs ob-tabs">
                  {[
                    { key: "book",   label: "委買委賣" },
                    { key: "trades", label: "成交明細" },
                  ].map(({ key, label }) => (
                    <button
                      key={key}
                      className={obTab === key ? "active" : ""}
                      onClick={() => setObTab(key)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {obTab === "book" ? (
                  <OrderBook data={orderbook} loading={obLoading} />
                ) : (
                  <TradeList trades={trades} />
                )}
              </div>
              <IntradayMiniChart
                data={intradayData}
                prevClose={orderbook.close != null && orderbook.change != null ? orderbook.close - orderbook.change : null}
              />
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
  const displayPrice = (price) => (price === 0 ? "市價" : price);

  return (
    <div className="ob-wrap">
      <div className="ob-header-row">
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

function IntradayMiniChart({ data, prevClose }) {
  const yDomain = (() => {
    if (!data.length) return ["auto", "auto"];
    const values = data.flatMap((d) => [d.price, d.average]).filter((v) => v != null);
    if (prevClose != null) values.push(prevClose);
    if (!values.length) return ["auto", "auto"];
    const min = Math.min(...values), max = Math.max(...values);
    const pad = Math.max((max - min) * 0.08, 0.5);
    return [min - pad, max + pad];
  })();
  const gradientOffset = (() => {
    if (prevClose == null || yDomain[0] === "auto") return 0.5;
    const [min, max] = yDomain;
    if (max === min) return 0.5;
    return Math.min(1, Math.max(0, (max - prevClose) / (max - min)));
  })();
  // 用 useMemo 固定住陣列參照：這個元件所在的父層因為委買委賣 WebSocket 更新會很頻繁重新
  // render，若每次 render 都重新產生一個新陣列，會讓 recharts 的 ResponsiveContainer 量測
  // 尺寸跟資料變化的偵測互相觸發，導致 "Maximum update depth exceeded" 無窮迴圈。
  const displayData = useMemo(() => padIntradayToFullDay(data), [data]);

  return (
    <div className="intraday-mini-wrap">
      <div className="ob-title" style={{ marginBottom: 6 }}>當日走勢</div>
      {data.length > 0 ? (
        <>
          <ResponsiveContainer width="100%" height={110}>
            <LineChart data={displayData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="terminalIntradayColor" x1="0" y1="0" x2="0" y2="1">
                  <stop offset={gradientOffset} stopColor="var(--up)" />
                  <stop offset={gradientOffset} stopColor="var(--down)" />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
              <XAxis dataKey="time" tick={{ fontSize: 9 }} interval="preserveStartEnd" />
              <YAxis domain={yDomain} tick={{ fontSize: 9 }} width={42} tickFormatter={(v) => v.toFixed(2)} />
              <Tooltip formatter={(v, name) => [`${v} 元`, name === "average" ? "均價" : "成交價"]} />
              {prevClose != null && <ReferenceLine y={prevClose} stroke="#888" strokeDasharray="4 4" />}
              <Line type="monotone" dataKey="average" stroke="#ccc" dot={false} strokeWidth={1} />
              <Line type="monotone" dataKey="price" stroke="url(#terminalIntradayColor)" dot={false} strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
          <ResponsiveContainer width="100%" height={36}>
            <BarChart data={displayData} margin={{ top: 0, right: 4, left: 0, bottom: 0 }}>
              <XAxis dataKey="time" hide />
              <YAxis width={42} tick={false} axisLine={false} tickLine={false} />
              <Bar dataKey="volume">
                {displayData.map((d, i) => (
                  <Cell key={i} fill={prevClose == null || d.price >= prevClose ? "var(--up)" : "var(--down)"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </>
      ) : (
        <p className="tl-loading">今日尚無分時資料</p>
      )}
    </div>
  );
}

function TradeList({ trades }) {
  if (!trades || trades.length === 0) {
    return <div className="tradelist-wrap"><p className="tl-empty">暫無成交明細</p></div>;
  }

  return (
    <div className="tradelist-wrap">
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
