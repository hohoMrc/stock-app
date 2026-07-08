import { useState, useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from "react";
import { createChart, CandlestickSeries, LineSeries, HistogramSeries } from "lightweight-charts";
import { getFuturesQuote, getFuturesCandles, getFuturesInstitutional } from "../api";
import { isFuturesTradingHours } from "../marketHours";

const MA_LINES = [
  { key: "ma5",   period: 5,  label: "MA5",   color: "#f59e0b" },
  { key: "ma20",  period: 20, label: "MA20",  color: "#facc15" },
  { key: "ma60",  period: 60, label: "MA60",  color: "#34d399" },
  { key: "ema5",  period: 5,  label: "EMA5",  color: "#a78bfa", ema: true },
  { key: "ema10", period: 10, label: "EMA10", color: "#fb923c", ema: true },
  { key: "ema20", period: 20, label: "EMA20", color: "#38bdf8", ema: true },
  { key: "ema60", period: 60, label: "EMA60", color: "#ef4444", ema: true },
];

function calcMA(data, period) {
  const result = [];
  for (let i = period - 1; i < data.length; i++) {
    const avg = data.slice(i - period + 1, i + 1).reduce((s, d) => s + d.close, 0) / period;
    result.push({ time: data[i].time ?? data[i].date, value: parseFloat(avg.toFixed(2)) });
  }
  return result;
}

function calcEMA(data, period) {
  const k = 2 / (period + 1);
  const result = [];
  let ema = null;
  for (let i = 0; i < data.length; i++) {
    if (ema === null) {
      if (i < period - 1) continue;
      ema = data.slice(0, period).reduce((s, d) => s + d.close, 0) / period;
    } else {
      ema = data[i].close * k + ema * (1 - k);
    }
    result.push({ time: data[i].time ?? data[i].date, value: parseFloat(ema.toFixed(2)) });
  }
  return result;
}

const WS_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  .replace(/^http/, "ws");

// lightweight-charts v5 不支援 timezone 選項，改在前端把 unix timestamp +8h
// 讓圖表顯示台北時間（圖表以為是 UTC，實際上是 UTC+8 local time）
const TW_OFFSET = 8 * 3600;
const shiftTime = (t) => (typeof t === "number" ? t + TW_OFFSET : t);

const TIMEFRAMES = [
  { key: "D",  label: "日K" },
  { key: "60", label: "60分" },
  { key: "30", label: "30分" },
  { key: "15", label: "15分" },
  { key: "5",  label: "5分" },
  { key: "1",  label: "1分" },
];

const PRODUCTS = [
  { key: "TXF", label: "台指期（近月）" },
  { key: "TMF", label: "微型台指（近月）" },
];

const IDENTITY_LABEL = { foreign: "外資", trust: "投信", dealer: "自營商" };
const IDENTITY_COLOR = { foreign: "#38bdf8", trust: "#f59e0b", dealer: "#a78bfa" };

function QuoteHeader({ quote, loading, livePrice, priceFlash }) {
  if (loading) return <div className="futures-quote-loading">載入中...</div>;
  if (!quote)  return null;
  const displayPrice = livePrice ?? quote.price;
  const change    = quote.prev_close ? Math.round(displayPrice - quote.prev_close) : quote.change;
  const changePct = quote.prev_close ? Math.round((displayPrice - quote.prev_close) / quote.prev_close * 10000) / 100 : quote.change_pct;
  const up = change >= 0;
  return (
    <div className="futures-quote">
      <div className="futures-quote-main">
        <span className="futures-symbol">{quote.symbol}</span>
        <span className="futures-name">{quote.name}</span>
        <span className={`futures-price ${up ? "up" : "down"} ${priceFlash ? `flash-${priceFlash}` : ""}`}>
          {displayPrice?.toLocaleString()}
        </span>
        <span className={`futures-change ${up ? "up" : "down"}`}>
          {up ? "▲" : "▼"} {Math.abs(change)} ({up ? "+" : ""}{changePct}%)
        </span>
        <span className="futures-live-dot" title="即時報價">●</span>
      </div>
      <div className="futures-quote-detail">
        <span>昨收 <b>{quote.prev_close?.toLocaleString()}</b></span>
        <span>開盤 <b>{quote.open?.toLocaleString()}</b></span>
        <span>最高 <b className="up">{quote.high?.toLocaleString()}</b></span>
        <span>最低 <b className="down">{quote.low?.toLocaleString()}</b></span>
        <span>成交量 <b>{quote.volume?.toLocaleString()}</b></span>
      </div>
    </div>
  );
}

const FuturesChart = forwardRef(function FuturesChart({ candles, timeframe, activeMA }, ref) {
  const containerRef    = useRef(null);
  const chartRef        = useRef(null);
  const candleSeriesRef = useRef(null);
  const lastBarRef      = useRef(null);
  const maSeriesMap     = useRef({});   // key → LineSeries
  const closesRef       = useRef([]);   // 最近 closes（滑動窗口，最大長度 max period）
  const emaStateRef     = useRef({});   // key → 上一根已確認的 EMA 值

  const MAX_PERIOD = Math.max(...MA_LINES.map(l => l.period));

  useImperativeHandle(ref, () => ({
    updateLastCandle(price) {
      if (!candleSeriesRef.current || !lastBarRef.current) return;
      const bar = lastBarRef.current;

      // nowSec 也用同樣的 +8h 偏移，與 bar.time（已 shift）比較
      const nowSec          = Math.floor(Date.now() / 1000) + TW_OFFSET;
      const bucketSecs      = parseInt(timeframe, 10) * 60;
      const expectedNext    = bar.time + bucketSecs;
      const isNewBar        = nowSec >= expectedNext;

      // 更新 K 棒
      let nextBar;
      if (isNewBar) {
        nextBar = { time: expectedNext, open: price, high: price, low: price, close: price };
        // 舊 bar 確認收盤，把舊收盤 push 進 closes，再 push 新價
        closesRef.current.push(bar.close, price);
        if (closesRef.current.length > MAX_PERIOD + 2)
          closesRef.current = closesRef.current.slice(-MAX_PERIOD - 2);
      } else {
        nextBar = {
          time:  bar.time,
          open:  bar.open,
          high:  Math.max(bar.high, price),
          low:   Math.min(bar.low,  price),
          close: price,
        };
        // 同一根：替換最後一個 close
        closesRef.current[closesRef.current.length - 1] = price;
      }
      lastBarRef.current = nextBar;
      candleSeriesRef.current.update(nextBar);

      // 更新 MA / EMA 線
      const closes = closesRef.current;
      MA_LINES.forEach(({ key, period, ema }) => {
        const series = maSeriesMap.current[key];
        if (!series) return;

        let val;
        if (ema) {
          const k = 2 / (period + 1);
          if (isNewBar) {
            // 舊 bar 確認：先用舊 bar.close 推進 ema，再用新價算 display
            const committed = bar.close * k + (emaStateRef.current[key] ?? bar.close) * (1 - k);
            emaStateRef.current[key] = committed;
            val = price * k + committed * (1 - k);
          } else {
            val = price * k + (emaStateRef.current[key] ?? price) * (1 - k);
          }
        } else {
          if (closes.length < period) return;
          val = closes.slice(-period).reduce((s, v) => s + v, 0) / period;
        }
        series.update({ time: nextBar.time, value: parseFloat(val.toFixed(2)) });
      });
    },
  }), [timeframe]);

  useEffect(() => {
    if (!containerRef.current || !candles.length) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current        = null;
      candleSeriesRef.current = null;
      lastBarRef.current      = null;
      maSeriesMap.current     = {};
    }

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height: 380,
      layout: { background: { color: "#1a1a2e" }, textColor: "#ccc" },
      grid:   { vertLines: { color: "#2a2a3e" }, horzLines: { color: "#2a2a3e" } },
      timeScale: {
        timeVisible:    timeframe !== "D",
        secondsVisible: false,
        borderColor:    "#444",
      },
      rightPriceScale: { borderColor: "#444" },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor:   "#ef4444",
      downColor: "#22c55e",
      borderUpColor:   "#ef4444",
      borderDownColor: "#22c55e",
      wickUpColor:   "#ef4444",
      wickDownColor: "#22c55e",
    });

    const volSeries = chart.addSeries(HistogramSeries, {
      priceFormat:     { type: "volume" },
      priceScaleId:    "vol",
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    // 把 unix timestamp 偏移 +8h，讓圖表顯示台北時間
    const shifted = candles.map(c => ({ ...c, time: shiftTime(c.time ?? c.date) }));

    const candleData = shifted.map(c => ({
      time:  c.time,
      open:  c.open,
      high:  c.high,
      low:   c.low,
      close: c.close,
    }));

    candleSeries.setData(candleData);
    volSeries.setData(shifted.map(c => ({
      time:  c.time,
      value: c.volume,
      color: c.close >= c.open ? "#ef4444aa" : "#22c55eaa",
    })));

    candleSeriesRef.current = candleSeries;
    lastBarRef.current      = candleData[candleData.length - 1] ?? null;

    // 初始化 closes 滑動窗口與 EMA 狀態
    const allCloses = shifted.map(c => c.close);
    closesRef.current = allCloses.slice(-(MAX_PERIOD + 2));
    emaStateRef.current = {};
    MA_LINES.filter(l => l.ema).forEach(({ key, period }) => {
      const k = 2 / (period + 1);
      let ema = null;
      for (let i = 0; i < allCloses.length; i++) {
        if (ema === null) {
          if (i < period - 1) continue;
          ema = allCloses.slice(0, period).reduce((s, v) => s + v, 0) / period;
        } else {
          ema = allCloses[i] * k + ema * (1 - k);
        }
      }
      emaStateRef.current[key] = ema;
    });

    // MA / EMA 線（用 shifted 讓時間也對齊）
    MA_LINES.forEach(({ key, period, color, ema }) => {
      if (!activeMA[key]) return;
      const lineData = ema ? calcEMA(shifted, period) : calcMA(shifted, period);
      if (!lineData.length) return;
      const s = chart.addSeries(LineSeries, {
        color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        lineStyle: ema ? 1 : 0,
      });
      s.setData(lineData);
      maSeriesMap.current[key] = s;
    });

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: containerRef.current?.clientWidth || 600 });
    });
    ro.observe(containerRef.current);

    chartRef.current = chart;
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; };
  }, [candles, timeframe, activeMA]);

  return <div ref={containerRef} className="futures-chart" />;
});

function InstitutionalChart({ data }) {
  if (!data.length) return <div className="futures-inst-empty">暫無法人資料</div>;

  const latest = data[data.length - 1];
  const roles  = ["foreign", "trust", "dealer"];

  return (
    <div className="futures-institutional">
      <h3 className="futures-section-title">三大法人台指期未沖銷淨部位（口）</h3>

      {/* 今日數字 */}
      <div className="inst-today">
        <span className="inst-date">{latest.date}</span>
        {roles.map(r => {
          const val = latest[r] ?? 0;
          return (
            <div key={r} className="inst-card">
              <span className="inst-label" style={{ color: IDENTITY_COLOR[r] }}>
                {IDENTITY_LABEL[r]}
              </span>
              <span className={`inst-value ${val >= 0 ? "up" : "down"}`}>
                {val >= 0 ? "+" : ""}{val?.toLocaleString()}
              </span>
            </div>
          );
        })}
      </div>

      {/* 近期趨勢 bar chart */}
      <div className="inst-bars">
        {data.slice(-15).map(d => (
          <div key={d.date} className="inst-bar-row">
            <span className="inst-bar-date">{d.date?.slice(5)}</span>
            {roles.map(r => {
              const val = d[r] ?? 0;
              const w   = Math.min(Math.abs(val) / 5000 * 100, 100);
              return (
                <div key={r} className="inst-bar-wrap" title={`${IDENTITY_LABEL[r]}: ${val}`}>
                  <div
                    className={`inst-bar ${val >= 0 ? "bar-up" : "bar-down"}`}
                    style={{ width: `${w}%`, backgroundColor: IDENTITY_COLOR[r] }}
                  />
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <div className="inst-legend">
        {roles.map(r => (
          <span key={r} style={{ color: IDENTITY_COLOR[r] }}>● {IDENTITY_LABEL[r]}</span>
        ))}
      </div>
    </div>
  );
}

export default function FuturesPage() {
  const [product,      setProduct]      = useState("TXF");
  const [timeframe,    setTimeframe]    = useState("60");
  const [quote,        setQuote]        = useState(null);
  const [candles,      setCandles]      = useState([]);
  const [institutional, setInstitutional] = useState([]);
  const [quoteLoading,  setQuoteLoading]  = useState(true);
  const [candleLoading, setCandleLoading] = useState(true);
  const [livePrice,    setLivePrice]    = useState(null);
  const [priceFlash,   setPriceFlash]   = useState(null); // "up" | "down"
  const [activeMA,     setActiveMA]     = useState({ ma5: false, ma20: false, ma60: false, ema5: false, ema10: true, ema20: false, ema60: true });
  const [error, setError] = useState(null);
  const [wsKey, setWsKey] = useState(0);   // 遞增觸發 WebSocket 重連
  const wsRef        = useRef(null);
  const prevPriceRef = useRef(null);
  const chartRef     = useRef(null);

  // 初始報價
  useEffect(() => {
    setQuoteLoading(true);
    setQuote(null);
    setLivePrice(null);
    prevPriceRef.current = null;
    getFuturesQuote(product)
      .then(r => { setQuote(r.data); setLivePrice(r.data.price); prevPriceRef.current = r.data.price; })
      .catch(e => setError(e?.response?.data?.detail || e.message))
      .finally(() => setQuoteLoading(false));
  }, [product]);

  // REST 輪詢報價（WebSocket 不穩定時的保底，每 5 秒）
  useEffect(() => {
    if (!isFuturesTradingHours()) return;
    const timer = setInterval(() => {
      getFuturesQuote(product).then(r => {
        const p = r.data?.price;
        if (!p) return;
        const prev = prevPriceRef.current;
        if (p !== prev) {
          setPriceFlash(prev == null ? null : p >= prev ? "up" : "down");
          setLivePrice(p);
          prevPriceRef.current = p;
          setTimeout(() => setPriceFlash(null), 400);
          chartRef.current?.updateLastCandle(p);
          setQuote(q => q ? { ...q, price: p,
            change:     q.prev_close ? Math.round(p - q.prev_close) : q.change,
            change_pct: q.prev_close ? Math.round((p - q.prev_close) / q.prev_close * 10000) / 100 : q.change_pct,
          } : q);
        }
      }).catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  }, [product]);

  // WebSocket 即時更新（wsKey 遞增觸發重連）
  useEffect(() => {
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    const ws = new WebSocket(`${WS_BASE}/ws/futures?product=${product}`);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      try {
        const data  = JSON.parse(e.data);
        if (data.event === "keepalive") return;   // 忽略心跳
        const trades = data.trades || [];
        if (!trades.length) return;
        const price = trades[trades.length - 1].price;
        if (!price) return;
        const prev = prevPriceRef.current;
        setPriceFlash(prev == null ? null : price >= prev ? "up" : "down");
        setLivePrice(price);
        prevPriceRef.current = price;
        setTimeout(() => setPriceFlash(null), 400);
        chartRef.current?.updateLastCandle(price);
        setQuote(q => q ? {
          ...q,
          price,
          change:     q.prev_close ? Math.round(price - q.prev_close) : q.change,
          change_pct: q.prev_close ? Math.round((price - q.prev_close) / q.prev_close * 10000) / 100 : q.change_pct,
        } : q);
      } catch (_) {}
    };
    ws.onerror = () => {};
    ws.onclose = () => {
      // 斷線後 3 秒自動重連
      setTimeout(() => setWsKey(k => k + 1), 3000);
    };
    return () => {
      ws.onclose = null;   // 清掉 onclose 避免 cleanup 時觸發重連
      ws.close();
      wsRef.current = null;
    };
  }, [product, wsKey]);

  useEffect(() => {
    getFuturesInstitutional()
      .then(r => setInstitutional(r.data.data || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    let retryTimer = null;
    const load = () => {
      setCandleLoading(true);
      getFuturesCandles(timeframe, product)
        .then(r => {
          const data = r.data.data || [];
          setCandles(data);
          // 交易時段若回空，15 秒後重試（開盤初期 API 需要一兩分鐘才有資料）
          if (data.length === 0 && timeframe !== "D" && isFuturesTradingHours()) {
            retryTimer = setTimeout(load, 15000);
          }
        })
        .catch(e => setError(e?.response?.data?.detail || e.message))
        .finally(() => setCandleLoading(false));
    };
    setCandles([]);
    load();
    return () => clearTimeout(retryTimer);
  }, [timeframe, product]);

  return (
    <div className="page futures-page">
      {/* 商品切換 */}
      <div className="futures-product-bar">
        {PRODUCTS.map(p => (
          <button
            key={p.key}
            className={`futures-product-btn ${product === p.key ? "active" : ""}`}
            onClick={() => setProduct(p.key)}
          >
            {p.label}
          </button>
        ))}
      </div>

      <QuoteHeader quote={quote} loading={quoteLoading} livePrice={livePrice} priceFlash={priceFlash} />

      {error && <p className="error">❌ {error}</p>}

      <div className="futures-tf-ma-row">
        <div className="futures-tf-bar">
          {TIMEFRAMES.map(tf => (
            <button
              key={tf.key}
              className={`futures-tf-btn ${timeframe === tf.key ? "active" : ""}`}
              onClick={() => setTimeframe(tf.key)}
            >
              {tf.label}
            </button>
          ))}
        </div>
        <div className="futures-ma-bar">
          {MA_LINES.map(({ key, label, color }) => (
            <button
              key={key}
              className={`futures-ma-btn ${activeMA[key] ? "active" : ""}`}
              style={{ "--ma-color": color }}
              onClick={() => setActiveMA(prev => ({ ...prev, [key]: !prev[key] }))}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {candleLoading
        ? <div className="futures-chart-loading">K 線載入中...</div>
        : candles.length === 0 && timeframe !== "D"
          ? <div className="futures-chart-empty">盤中 K 線資料暫無（交易時段 08:45–13:45）</div>
          : <FuturesChart ref={chartRef} candles={candles} timeframe={timeframe} activeMA={activeMA} />
      }

      <InstitutionalChart data={institutional} />
    </div>
  );
}
