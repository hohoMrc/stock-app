import { useState, useEffect, useRef, useMemo } from "react";
import { LineChart, Line, BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, ReferenceDot } from "recharts";
import CandlestickChart from "./CandlestickChart";
import AlertModal from "./AlertModal";
import { getStock, getHistory, analyzeStock, getInstitutionalTrades, getIntradayChart, getIntradayCandles } from "../api";
import { isTradingHours } from "../marketHours";

const INTERVAL_CONFIG = {
  "15m": { fetchPeriod: "1mo", defaultPeriod: "5d",  periods: ["5d","1mo"] },
  "60m": { fetchPeriod: "3mo", defaultPeriod: "5d",  periods: ["5d","1mo","3mo"] },
  "1d":  { fetchPeriod: "1y",  defaultPeriod: "3mo", periods: ["1mo","3mo","6mo","1y"] },
  "1wk": { fetchPeriod: "2y",  defaultPeriod: "1y",  periods: ["3mo","6mo","1y","2y"] },
  "1mo": { fetchPeriod: "5y",  defaultPeriod: "2y",  periods: ["1y","2y","5y"] },
};

const SCAN_DEFAULT_MA = {
  bird_beak: { ma5: true,  ma10: false, ma20: true,  ma30: false, ma60: false, ema10: false, ema60: false },
  near_ema60: { ma5: false, ma10: false, ma20: false, ma30: false, ma60: false, ema10: true,  ema60: true  },
};

// 日K圖的歷史資料在後端有快取，可能比報價舊；用最新報價把最後一根 K 棒校正成即時值，
// 開頁當下就套用一次，不用等第一次輪詢才校正，避免畫面先顯示舊資料又突然跳成新的。
function mergeLiveBar(historyArr, info, interval) {
  if (interval !== "1d" || !info?.quote_date || !info.open || !info.price) return historyArr;
  if (!historyArr || historyArr.length === 0) return historyArr;
  const newBar = {
    date: info.quote_date, open: info.open,
    high: info.high ?? info.price, low: info.low ?? info.price,
    close: info.price, volume: info.volume ?? 0,
  };
  const last = historyArr[historyArr.length - 1];
  if (last.date === newBar.date) return [...historyArr.slice(0, -1), newBar];
  if (newBar.date > last.date) return [...historyArr, newBar];
  return historyArr;
}

// 分時圖的時間軸要一開始就固定畫到收盤（09:00~13:30），不要隨著資料進來越畫越長，
// 所以把還沒到的時間點也補成空值放進資料陣列，recharts 遇到 null 就自然不畫、留白，
// 讓線隨時間慢慢往右延伸，但橫軸範圍/刻度全程都不會變動。
function padIntradayToFullDay(intradayData) {
  const map = new Map(intradayData.map((d) => [d.time, d]));
  const lastRealTime = intradayData.length ? intradayData[intradayData.length - 1].time : null;
  const result = [];
  let lastKnown = null;
  for (let mins = 9 * 60; mins <= 13 * 60 + 30; mins++) {
    const time = `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
    const existing = map.get(time);
    if (existing) {
      lastKnown = existing;
      result.push(existing);
    } else if (lastRealTime != null && time <= lastRealTime) {
      // 已經過去的時間但沒有K棒（例如漲停/跌停鎖死沒成交），價格維持前一筆不變、量為0，
      // 不能留空值，不然 recharts 遇到 null 會斷線，看起來像斷點虛線。
      result.push(lastKnown ? { time, price: lastKnown.price, average: lastKnown.average, volume: 0 } : { time, price: null, average: null, volume: null });
    } else {
      // 還沒到的時間，維持空白讓線不要畫過去
      result.push({ time, price: null, average: null, volume: null });
    }
  }
  return result;
}

// 15分K/60分K：今天的棒直接整批換成 Fugle 即時分鐘K棒（比 yfinance 準且沒有快取延遲），
// 較早之前幾天的棒維持原本 yfinance 資料，用時間戳比對切開，不用管兩邊分桶邊界是否對齊。
function mergeIntradayBars(historyArr, todayCandles) {
  if (!todayCandles || todayCandles.length === 0) return historyArr;
  const cutoff = todayCandles[0].date;
  const past = (historyArr || []).filter((r) => r.date < cutoff);
  return [...past, ...todayCandles];
}

export default function StockDetail({ ticker, scanContext = null, onBack, onIndustry, watchlist = [], onToggleWatch, onPaperTrade, username, onRequireLogin }) {
  const [info, setInfo] = useState(null);
  const [showAlertModal, setShowAlertModal] = useState(false);
  const [mobileTab, setMobileTab] = useState("quote"); // 手機版分頁："quote"|"kline"|"inst"|"ai"，桌面版不生效
  const [chartOptionsExpanded, setChartOptionsExpanded] = useState(false); // 手機版K線週期「更多」收合，桌面版不生效
  const [history, setHistory] = useState([]);
  const [analysis, setAnalysis] = useState("");
  const [period, setPeriod] = useState("3mo");
  const [chartType, setChartType] = useState("candle"); // "candle" | "line"
  const [interval, setIntervalKey] = useState("1d");     // "1d" | "1wk" | "1mo"
  const [analyzing, setAnalyzing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [chartLoading, setChartLoading] = useState(false); // 只有切換K線區間/週期時用，不擋整頁
  const [live, setLive] = useState(false);   // 是否正在即時刷新
  const pollRef = useRef(null);
  const lastTickerRef = useRef(null);
  const [instTrades, setInstTrades] = useState([]);
  const [instLoading, setInstLoading] = useState(false);
  const [intradayData, setIntradayData] = useState([]);
  const [intradayLoading, setIntradayLoading] = useState(false);
  const intradayPollRef = useRef(null);
  // useMemo 固定陣列參照，避免每次 render 都產生新陣列讓 recharts 的 ResponsiveContainer
  // 尺寸量測跟資料變化偵測互相觸發，導致無窮迴圈（看盤頁已實際踩到這個問題）。
  // 必須放在任何 early return 之前，不然 hooks 呼叫順序在不同 render 之間會不一致。
  const intradayDisplayData = useMemo(() => padIntradayToFullDay(intradayData), [intradayData]);

  useEffect(() => {
    const cfg = INTERVAL_CONFIG[interval];
    setPeriod(cfg.defaultPeriod);
    const intradayTimeframe = interval === "15m" ? "15" : interval === "60m" ? "60" : null;
    // 只有真的換股票才要擋整頁顯示「載入中」；單純切K線區間/週期（ticker沒變）
    // 不用重打 getStock（報價跟interval無關），也不用整頁重載，只換圖表資料即可直接切換。
    const tickerChanged = lastTickerRef.current !== ticker;
    lastTickerRef.current = ticker;

    let alive = true;
    const load = async () => {
      if (tickerChanged) setLoading(true); else setChartLoading(true);
      try {
        let currentInfo = info;
        if (tickerChanged) {
          const infoRes = await getStock(ticker);
          if (!alive) return;
          currentInfo = infoRes.data;
          setInfo(currentInfo);
        }
        const histRes = await getHistory(ticker, cfg.fetchPeriod, interval);
        if (!alive) return;
        let hist = histRes.data.data;
        if (interval === "1d") {
          hist = mergeLiveBar(hist, currentInfo, interval);
        } else if (intradayTimeframe) {
          try {
            const candleRes = await getIntradayCandles(ticker, intradayTimeframe);
            if (!alive) return;
            hist = mergeIntradayBars(hist, candleRes.data.candles);
          } catch (_) {}
        }
        setHistory(hist);
      } finally {
        if (alive) { setLoading(false); setChartLoading(false); }
      }
    };
    load();

    // 每 10 秒自動刷新報價（交易時段才會真的打 API），日K/15分K/60分K 同時校正圖表最後幾根棒。
    // isTradingHours() 要放在 interval callback 裡面每次都重新判斷，不能只在 effect 掛載當下
    // 判斷一次——不然使用者若在非交易時段開著頁面，等到開盤時刻到了也不會自動開始輪詢。
    clearInterval(pollRef.current);
    setLive(isTradingHours());
    pollRef.current = setInterval(async () => {
      if (!isTradingHours()) { setLive(false); return; }
      setLive(true);
      try {
        const res = await getStock(ticker);
        setInfo(res.data);
        if (interval === "1d") {
          setHistory((prev) => mergeLiveBar(prev, res.data, interval));
        } else if (intradayTimeframe) {
          const candleRes = await getIntradayCandles(ticker, intradayTimeframe);
          setHistory((prev) => mergeIntradayBars(prev, candleRes.data.candles));
        }
      } catch (_) {}
    }, 10_000);
    return () => { alive = false; clearInterval(pollRef.current); };
  }, [ticker, interval]);

  // 三大法人買賣超（近30天，只需在切換股票時抓一次，不用跟報價一樣輪詢）
  useEffect(() => {
    let alive = true;
    setInstLoading(true);
    getInstitutionalTrades(ticker, 30)
      .then((res) => { if (alive) setInstTrades(res.data.records); })
      .catch(() => { if (alive) setInstTrades([]); })
      .finally(() => { if (alive) setInstLoading(false); });
    return () => { alive = false; };
  }, [ticker]);

  // 當日分時走勢圖，切換股票時抓一次，交易時段內每15秒刷新
  useEffect(() => {
    let alive = true;
    const load = () =>
      getIntradayChart(ticker)
        .then((res) => { if (alive) setIntradayData(res.data.points); })
        .catch(() => { if (alive) setIntradayData([]); });
    setIntradayLoading(true);
    load().finally(() => { if (alive) setIntradayLoading(false); });

    clearInterval(intradayPollRef.current);
    intradayPollRef.current = setInterval(() => { if (isTradingHours()) load(); }, 15_000);
    return () => { alive = false; clearInterval(intradayPollRef.current); };
  }, [ticker]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setAnalysis("");
    try {
      const res = await analyzeStock(ticker);
      setAnalysis(res.data.analysis);
    } catch (e) {
      setAnalysis("分析失敗，請確認 API Key 是否設定正確。");
    } finally {
      setAnalyzing(false);
    }
  };

  if (loading) return <div className="page"><p>載入中...</p></div>;
  if (!info) return <div className="page"><p>無法載入資料</p></div>;

  // Y軸範圍要涵蓋昨收，不然股價跳空時參考線會被裁到圖外，看不出跟昨收的落差
  const intradayPrevClose = info.price != null && info.change != null ? info.price - info.change : null;
  // 今日振幅%，手機版行情分頁的簡易統計列用
  const todayAmplitudePct = (info.high != null && info.low != null && intradayPrevClose)
    ? (((info.high - info.low) / intradayPrevClose) * 100).toFixed(2)
    : null;
  // 三關價：用前一交易日高低算出上關/中關/下關（費波那契 0.382），常見於當沖找支撐壓力
  const intradayGates = (() => {
    if (info.prev_high == null || info.prev_low == null) return null;
    const range = info.prev_high - info.prev_low;
    return {
      upper: +(info.prev_high + range * 0.382).toFixed(2),
      mid:   +((info.prev_high + info.prev_low) / 2).toFixed(2),
      lower: +(info.prev_low - range * 0.382).toFixed(2),
    };
  })();
  const intradayYDomain = (() => {
    if (!intradayData.length) return ["auto", "auto"];
    const values = intradayData.flatMap((d) => [d.price, d.average]).filter((v) => v != null);
    if (intradayPrevClose != null) values.push(intradayPrevClose);
    if (intradayGates) values.push(intradayGates.upper, intradayGates.mid, intradayGates.lower);
    if (!values.length) return ["auto", "auto"];
    const min = Math.min(...values), max = Math.max(...values);
    const pad = Math.max((max - min) * 0.08, 0.5);
    return [min - pad, max + pad];
  })();
  // 價格線紅漲綠跌：用漸層在昨收的 Y 座標分色，不用逐點判斷
  const intradayGradientOffset = (() => {
    if (intradayPrevClose == null || intradayYDomain[0] === "auto") return 0.5;
    const [min, max] = intradayYDomain;
    if (max === min) return 0.5;
    return Math.min(1, Math.max(0, (max - intradayPrevClose) / (max - min)));
  })();
  // Y軸只標上緣/中間/下緣三個刻度，配合 AxisEdgeTick 把上下緣畫成色塊，仿看盤App樣式
  const intradayTicks = intradayYDomain[0] === "auto" ? undefined : (() => {
    const [min, max] = intradayYDomain;
    return [min, (min + max) / 2, max].map((v) => +v.toFixed(2));
  })();
  // 當天最高/最低點，標上浮動色塊價格牌
  const intradayHighPoint = intradayData.reduce((a, d) => (d.price != null && (!a || d.price > a.price) ? d : a), null);
  const intradayLowPoint  = intradayData.reduce((a, d) => (d.price != null && (!a || d.price < a.price) ? d : a), null);

  return (
    <div className="page">
      <button className="back-btn" onClick={onBack}>← 返回</button>

      <div className="stock-header">
        <div>
          <div className="stock-name-row">
            <h2>{info.name}</h2>
            <span className="price">{info.price} 元</span>
            {info.change != null && info.change_pct != null && (
              <span className={`price-change ${info.change > 0 ? "up" : info.change < 0 ? "down" : ""}`}>
                {info.change > 0 ? "▲" : info.change < 0 ? "▼" : ""}
                {Math.abs(info.change)}（{info.change_pct > 0 ? "+" : ""}{info.change_pct}%）
              </span>
            )}
            {live && <span className="live-dot" title="即時報價自動更新中">●</span>}
            {onToggleWatch && (
              <button
                className={`watch-btn ${watchlist.includes(ticker) ? "watched" : ""}`}
                onClick={() => onToggleWatch(ticker)}
                title={watchlist.includes(ticker) ? "從自選清單移除" : "加入自選清單"}
              >
                {watchlist.includes(ticker) ? "★ 已加入" : "☆ 加入自選"}
              </button>
            )}
            {onPaperTrade && (
              <button className="paper-trade-btn" onClick={() => onPaperTrade(ticker)}>
                模擬下單
              </button>
            )}
            <button
              className="paper-trade-btn"
              onClick={() => (username ? setShowAlertModal(true) : onRequireLogin?.())}
            >
              🔔 設定提醒
            </button>
          </div>
          <span className="ticker-badge">{ticker}</span>
          {info.source && (
            <span className="source-badge" title="資料來源">
              {{ fugle: "富邦 Fugle", twse: "TWSE", yfinance: "Yahoo Finance" }[info.source] ?? info.source}
            </span>
          )}
          {info.is_attention             && <span className="warn-badge attention-badge"   title="注意股">注意股</span>}
          {info.is_disposition           && <span className="warn-badge disposition-badge" title="處置股">處置股</span>}
          {info.is_unusually_recommended && <span className="warn-badge attention-badge"   title="異常推介股">異常推介</span>}
          {info.is_specific_abnormally   && <span className="warn-badge disposition-badge" title="特定異常股">特定異常</span>}
          {info.is_halted                && <span className="warn-badge halted-badge"       title="暫停交易">暫停交易</span>}
          {info.industry && (
            <span
              className="industry-badge clickable"
              onClick={() => onIndustry && onIndustry(info.industry, ticker)}
              title="點擊查看同產業個股"
            >
              {info.industry}
            </span>
          )}
        </div>
      </div>

      <div className="mobile-detail-tabs">
        {[
          { key: "quote", label: "行情" },
          { key: "kline", label: "K線" },
          { key: "inst",  label: "法人" },
          { key: "ai",    label: "AI分析" },
        ].map(({ key, label }) => (
          <button key={key} className={mobileTab === key ? "active" : ""} onClick={() => setMobileTab(key)}>
            {label}
          </button>
        ))}
      </div>

      <div className="mobile-stat-row">
        <div><span>開盤</span><b>{info.open ?? "—"}</b></div>
        <div><span>最高</span><b className="up">{info.high ?? "—"}</b></div>
        <div><span>最低</span><b className="down">{info.low ?? "—"}</b></div>
        <div><span>振幅</span><b>{todayAmplitudePct != null ? `${todayAmplitudePct}%` : "—"}</b></div>
        <div><span>成交量(張)</span><b>{info.volume_zhang != null ? info.volume_zhang.toLocaleString() : "—"}</b></div>
      </div>

      <div className={`chart-section intraday-section tab-quote ${mobileTab === "quote" ? "mobile-active" : ""}`}>
        <div className="chart-header">
          <h3>當日走勢</h3>
          {intradayData.length > 0 && intradayData[intradayData.length - 1].average != null && (
            <span className="intraday-avg">均價 {intradayData[intradayData.length - 1].average}</span>
          )}
        </div>

        {intradayLoading && intradayData.length === 0 ? (
          <p className="loading-hint">載入中...</p>
        ) : intradayData.length > 0 ? (
          <>
            <ResponsiveContainer width="100%" height={180}>
              {/* top/bottom margin 留多一點，不然當天最高/最低點的浮動價格牌太靠近上下緣時會被裁掉 */}
              <LineChart data={intradayDisplayData} margin={{ top: 24, right: 4, left: 0, bottom: 20 }}>
                <defs>
                  <linearGradient id="intradayPriceColor" x1="0" y1="0" x2="0" y2="1">
                    <stop offset={intradayGradientOffset} stopColor="var(--up)" />
                    <stop offset={intradayGradientOffset} stopColor="var(--down)" />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
                <XAxis dataKey="time" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                <YAxis
                  domain={intradayYDomain}
                  ticks={intradayTicks}
                  width={55}
                  tick={<AxisEdgeTick ticks={intradayTicks} />}
                />
                <Tooltip
                  formatter={(v, name) => [`${v} 元`, name === "average" ? "均價" : "成交價"]}
                  labelFormatter={(l) => `${l}`}
                />
                {intradayPrevClose != null && (
                  <ReferenceLine y={intradayPrevClose} stroke="#888" strokeDasharray="4 4" />
                )}
                {intradayGates && (
                  <>
                    <ReferenceLine y={intradayGates.upper} stroke="#facc15" strokeDasharray="2 3" label={{ value: `上關 ${intradayGates.upper}`, position: "insideBottomLeft", fontSize: 10, fill: "#facc15" }} />
                    <ReferenceLine y={intradayGates.mid} stroke="#a78bfa" strokeDasharray="2 3" label={{ value: `中關 ${intradayGates.mid}`, position: "insideBottomLeft", fontSize: 10, fill: "#a78bfa" }} />
                    <ReferenceLine y={intradayGates.lower} stroke="#facc15" strokeDasharray="2 3" label={{ value: `下關 ${intradayGates.lower}`, position: "insideBottomLeft", fontSize: 10, fill: "#facc15" }} />
                  </>
                )}
                <Line type="monotone" dataKey="average" stroke="#ccc" dot={false} strokeWidth={1} isAnimationActive={false} />
                <Line type="monotone" dataKey="price" stroke="url(#intradayPriceColor)" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                {intradayHighPoint && (
                  <ReferenceDot x={intradayHighPoint.time} y={intradayHighPoint.price} r={0}
                    label={<PriceBadge value={intradayHighPoint.price} color="var(--up)" dy={-12} />} />
                )}
                {intradayLowPoint && (
                  <ReferenceDot x={intradayLowPoint.time} y={intradayLowPoint.price} r={0}
                    label={<PriceBadge value={intradayLowPoint.price} color="var(--down)" dy={12} />} />
                )}
              </LineChart>
            </ResponsiveContainer>
            <ResponsiveContainer width="100%" height={60}>
              <BarChart data={intradayDisplayData} margin={{ top: 0, right: 4, left: 0, bottom: 0 }}>
                <XAxis dataKey="time" hide />
                <YAxis width={55} tick={false} axisLine={false} tickLine={false} />
                <Bar dataKey="volume">
                  {intradayDisplayData.map((d, i) => (
                    <Cell key={i} fill={intradayPrevClose == null || d.price >= intradayPrevClose ? "var(--up)" : "var(--down)"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </>
        ) : (
          <p className="no-data">今日尚無分時資料</p>
        )}
      </div>

      <div className={`chart-section tab-kline ${mobileTab === "kline" ? "mobile-active" : ""}`}>
        <div className="chart-header">
          <div className="chart-header-left">
            <h3>股價走勢</h3>
            <div className="chart-type-btns">
              {[
                { label: "日K",   type: "candle", iv: "1d" },
                { label: "週K",   type: "candle", iv: "1wk" },
                { label: "月K",   type: "candle", iv: "1mo" },
              ].map(({ label, type, iv }) => (
                <button
                  key={label}
                  className={(chartType === type && (type === "line" || interval === iv)) ? "active" : ""}
                  onClick={() => { setChartType(type); if (type === "candle") setIntervalKey(iv); }}
                >
                  {label}
                </button>
              ))}
              <button
                className={`chart-more-toggle ${chartOptionsExpanded ? "active" : ""}`}
                onClick={() => setChartOptionsExpanded((v) => !v)}
              >
                更多 {chartOptionsExpanded ? "▴" : "▾"}
              </button>
            </div>
          </div>
          <div className={`chart-more-section ${chartOptionsExpanded ? "expanded" : ""}`}>
            <div className="chart-type-btns">
              {[
                { label: "15分K", type: "candle", iv: "15m" },
                { label: "60分K", type: "candle", iv: "60m" },
                { label: "折線",  type: "line",   iv: "1d" },
              ].map(({ label, type, iv }) => (
                <button
                  key={label}
                  className={(chartType === type && (type === "line" || interval === iv)) ? "active" : ""}
                  onClick={() => { setChartType(type); if (type === "candle") setIntervalKey(iv); }}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="period-btns">
              {INTERVAL_CONFIG[interval].periods.map((p) => (
                <button
                  key={p}
                  className={period === p ? "active" : ""}
                  onClick={() => setPeriod(p)}
                >
                  {{ "5d":"5天","1mo":"1個月","3mo":"3個月","6mo":"6個月","1y":"1年","2y":"2年","5y":"5年" }[p]}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div style={{ opacity: chartLoading ? 0.5 : 1, transition: "opacity 0.15s" }}>
        {history.length > 0 ? (
          chartType === "candle" ? (
            <CandlestickChart data={history} period={period} interval={interval} height={320} defaultMA={SCAN_DEFAULT_MA[scanContext] ?? null} />
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={history}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) => {
                    const [, m, d] = v.split("-");
                    return `${parseInt(m)}月${parseInt(d)}日`;
                  }}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={["auto", "auto"]}
                  tick={{ fontSize: 11 }}
                  width={65}
                  tickFormatter={(v) => `${v} 元`}
                />
                <Tooltip
                  formatter={(v) => [`${v} 元`, "收盤價"]}
                  labelFormatter={(l) => {
                    const [y, m, d] = l.split("-");
                    return `${y}年${parseInt(m)}月${parseInt(d)}日`;
                  }}
                />
                <Line type="monotone" dataKey="close" stroke="#2563eb" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          )
        ) : (
          <p className="no-data">無股價資料</p>
        )}
        </div>
      </div>

      <div className={`info-grid tab-quote ${mobileTab === "quote" ? "mobile-active" : ""}`}>
        <InfoItem label="52週高" value={info.week_52_high ?? "—"} />
        <InfoItem label="52週低" value={info.week_52_low ?? "—"} />
        <InfoItem label="本益比" value={info.pe_ratio ?? "—"} />
        <InfoItem label="股價淨值比" value={info.pb_ratio ?? "—"} />
        <InfoItem label="殖利率" value={info.dividend_yield != null ? `${info.dividend_yield}%` : "—"} />
        <InfoItem
          label="資券使用率"
          value={
            info.margin_balance != null && info.margin_quota
              ? `${((info.margin_balance / info.margin_quota) * 100).toFixed(1)}%`
              : "—"
          }
        />
        <InfoItem label="融資餘額(張)" value={info.margin_balance != null ? info.margin_balance.toLocaleString() : "—"} />
        <InfoItem label="融券餘額(張)" value={info.short_balance != null ? info.short_balance.toLocaleString() : "—"} />
        <InfoItem
          label="下次除權息"
          value={
            info.next_ex_dividend_date
              ? `${info.next_ex_dividend_date}${info.next_ex_dividend_cash != null ? `（${info.next_ex_dividend_cash}元）` : ""}`
              : "—"
          }
        />
      </div>

      {!instLoading && instTrades.length > 0 && (
        <div className={`institutional-section tab-inst ${mobileTab === "inst" ? "mobile-active" : ""}`}>
          <h3>三大法人買賣超（近{instTrades.length}個交易日，張）</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={instTrades} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11 }}
                tickFormatter={(v) => {
                  const [, m, d] = v.split("-");
                  return `${parseInt(m)}/${parseInt(d)}`;
                }}
              />
              <YAxis tick={{ fontSize: 11 }} width={50} />
              <Tooltip
                labelFormatter={(l) => {
                  const [y, m, d] = l.split("-");
                  return `${y}年${parseInt(m)}月${parseInt(d)}日`;
                }}
                formatter={(v, name) => {
                  const label = { foreign_net: "外資", trust_net: "投信", dealer_net: "自營商", total_net: "合計" }[name] || name;
                  return [`${v} 張`, label];
                }}
              />
              <Bar dataKey="total_net" name="total_net">
                {instTrades.map((r, i) => (
                  <Cell key={i} fill={r.total_net >= 0 ? "#f87171" : "#4ade80"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <table className="inst-table">
            <thead>
              <tr>
                <th>日期</th><th>外資</th><th>投信</th><th>自營商</th><th>合計</th>
              </tr>
            </thead>
            <tbody>
              {[...instTrades].reverse().map((r) => (
                <tr key={r.date}>
                  <td>{r.date.slice(5)}</td>
                  <td className={r.foreign_net > 0 ? "up" : r.foreign_net < 0 ? "down" : ""}>{r.foreign_net}</td>
                  <td className={r.trust_net > 0 ? "up" : r.trust_net < 0 ? "down" : ""}>{r.trust_net}</td>
                  <td className={r.dealer_net > 0 ? "up" : r.dealer_net < 0 ? "down" : ""}>{r.dealer_net}</td>
                  <td className={r.total_net > 0 ? "up" : r.total_net < 0 ? "down" : ""}>{r.total_net}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className={`analysis-section tab-ai ${mobileTab === "ai" ? "mobile-active" : ""}`}>
        <div className="analysis-header">
          <h3>AI 分析</h3>
          <button onClick={handleAnalyze} disabled={analyzing} className="analyze-btn">
            {analyzing ? "分析中..." : "開始分析"}
          </button>
        </div>
        {analysis && (
          <div className="analysis-content">
            {analysis.split("\n").map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>
        )}
        {!analysis && !analyzing && (
          <p className="analysis-hint">點擊「開始分析」讓 AI 幫你分析這支股票</p>
        )}
      </div>

      {showAlertModal && (
        <AlertModal
          ticker={ticker}
          name={info.name}
          onClose={() => setShowAlertModal(false)}
        />
      )}
    </div>
  );
}

function InfoItem({ label, value }) {
  return (
    <div className="info-item">
      <span className="info-label">{label}</span>
      <span className="info-value">{value}</span>
    </div>
  );
}

// 分時圖 Y 軸上/下緣刻度畫成色塊（仿看盤App樣式），中間刻度維持普通文字
function AxisEdgeTick({ x, y, payload, ticks }) {
  const isTop    = !!ticks && payload.value === ticks[ticks.length - 1];
  const isBottom = !!ticks && payload.value === ticks[0];
  const label = payload.value.toFixed(2);
  if (!isTop && !isBottom) {
    return <text x={x} y={y} dy={3} textAnchor="end" fontSize={10} fill="#94a3b8">{label}</text>;
  }
  const color = isTop ? "var(--up)" : "var(--down)";
  const w = label.length * 6 + 8;
  return (
    <g transform={`translate(${x - w},${y - 8})`}>
      <rect width={w} height={16} rx={3} fill={color} />
      <text x={w / 2} y={11} textAnchor="middle" fontSize={10} fontWeight={700} fill="#04202b">{label}</text>
    </g>
  );
}

// 分時圖最高/最低點的浮動價格牌
function PriceBadge({ value, color, dy = 0, viewBox }) {
  if (!viewBox) return null;
  const label = String(value);
  const w = label.length * 6 + 10;
  const x = viewBox.x, y = viewBox.y + dy;
  return (
    <g transform={`translate(${x - w / 2},${y - 8})`}>
      <rect width={w} height={16} rx={3} fill={color} />
      <text x={w / 2} y={11} textAnchor="middle" fontSize={10} fontWeight={700} fill="#04202b">{label}</text>
    </g>
  );
}
