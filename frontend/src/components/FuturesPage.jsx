import { useState, useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from "react";
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from "lightweight-charts";
import {
  getFuturesQuote, getFuturesCandles, getFuturesInstitutional, getUtBotSignals, getSupertrendSignals,
  placeFuturesOrder, getFuturesPaperAccount, getFuturesPaperPositions,
} from "../api";
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

const KD_PERIOD  = 9;
const KD_K_COLOR = "#fb7185";
const KD_D_COLOR = "#22d3ee";

// 台式KD：RSV 用 9 根highest high/lowest low，K/D 用 1/3 平滑（跟慢速隨機指標同概念）
function calcKD(data, period = KD_PERIOD) {
  const result = [];
  let k = 50, d = 50;
  for (let i = period - 1; i < data.length; i++) {
    let high = -Infinity, low = Infinity;
    for (let j = i - period + 1; j <= i; j++) {
      if (data[j].high > high) high = data[j].high;
      if (data[j].low  < low)  low  = data[j].low;
    }
    const rsv = high === low ? 50 : (data[i].close - low) / (high - low) * 100;
    k = k * (2 / 3) + rsv * (1 / 3);
    d = d * (2 / 3) + k * (1 / 3);
    result.push({ time: data[i].time ?? data[i].date, k: parseFloat(k.toFixed(2)), d: parseFloat(d.toFixed(2)) });
  }
  return result;
}

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

// UT Bot / SuperTrend：跟後端 app/services/futures_signals.py 同一套邏輯移植到前端，
// 直接用畫面上的日K算，這樣才能把訊號畫在走勢圖上（後端只存「當天有沒有觸發」，沒有整條線）。
const UT_BOT_ATR_PERIOD = 11, UT_BOT_MULT = 2;
const SUPERTREND_ATR_PERIOD = 10, SUPERTREND_MULT = 3;

function calcTrueRange(data) {
  const tr = [data[0].high - data[0].low];
  for (let i = 1; i < data.length; i++) {
    const h = data[i].high, l = data[i].low, pc = data[i - 1].close;
    tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
  }
  return tr;
}

function calcRma(values, period) {
  const result = new Array(values.length).fill(null);
  if (values.length < period) return result;
  let seed = 0;
  for (let i = 0; i < period; i++) seed += values[i];
  result[period - 1] = seed / period;
  for (let i = period; i < values.length; i++) {
    result[i] = (result[i - 1] * (period - 1) + values[i]) / period;
  }
  return result;
}

function calcUtBot(data, period = UT_BOT_ATR_PERIOD, mult = UT_BOT_MULT) {
  const atr = calcRma(calcTrueRange(data), period);
  const stop = new Array(data.length).fill(null);
  const line = [], markers = [];
  let firstValid = null;

  for (let i = 0; i < data.length; i++) {
    if (atr[i] == null) continue;
    const src = data[i].close, nLoss = mult * atr[i];
    if (firstValid === null) {
      stop[i] = src - nLoss;
      firstValid = i;
    } else {
      const prevStop = stop[i - 1], prevSrc = data[i - 1].close;
      if (src > prevStop && prevSrc > prevStop) stop[i] = Math.max(prevStop, src - nLoss);
      else if (src < prevStop && prevSrc < prevStop) stop[i] = Math.min(prevStop, src + nLoss);
      else stop[i] = src > prevStop ? src - nLoss : src + nLoss;

      const crossoverUp   = src > stop[i] && prevSrc <= prevStop;
      const crossoverDown = stop[i] > src && prevStop <= prevSrc;
      if (src > stop[i] && crossoverUp) {
        markers.push({ time: data[i].time, position: "belowBar", color: "#f59e0b", shape: "arrowUp", text: "UT多" });
      } else if (src < stop[i] && crossoverDown) {
        markers.push({ time: data[i].time, position: "aboveBar", color: "#f59e0b", shape: "arrowDown", text: "UT空" });
      }
    }
    line.push({ time: data[i].time, value: parseFloat(stop[i].toFixed(1)) });
  }
  return { line, markers };
}

function calcSuperTrend(data, period = SUPERTREND_ATR_PERIOD, mult = SUPERTREND_MULT) {
  const atr = calcRma(calcTrueRange(data), period);
  const finalUpper = new Array(data.length).fill(null);
  const finalLower = new Array(data.length).fill(null);
  const trendUp    = new Array(data.length).fill(null);
  const line = [], markers = [];
  let first = null;

  for (let i = 0; i < data.length; i++) {
    if (atr[i] == null) continue;
    const hl2 = (data[i].high + data[i].low) / 2;
    const basicUpper = hl2 + mult * atr[i], basicLower = hl2 - mult * atr[i];
    const close = data[i].close;

    if (first === null) {
      finalUpper[i] = basicUpper;
      finalLower[i] = basicLower;
      trendUp[i] = close > basicUpper;
      first = i;
    } else {
      const prevClose = data[i - 1].close;
      const prevFu = finalUpper[i - 1], prevFl = finalLower[i - 1];
      finalUpper[i] = (basicUpper < prevFu || prevClose > prevFu) ? basicUpper : prevFu;
      finalLower[i] = (basicLower > prevFl || prevClose < prevFl) ? basicLower : prevFl;

      const prevTrendUp = trendUp[i - 1];
      trendUp[i] = prevTrendUp ? (close >= finalLower[i]) : (close > finalUpper[i]);

      if (trendUp[i] && !prevTrendUp) {
        markers.push({ time: data[i].time, position: "belowBar", color: "#a78bfa", shape: "arrowUp", text: "ST多" });
      } else if (!trendUp[i] && prevTrendUp) {
        markers.push({ time: data[i].time, position: "aboveBar", color: "#a78bfa", shape: "arrowDown", text: "ST空" });
      }
    }
    line.push({ time: data[i].time, value: parseFloat((trendUp[i] ? finalLower[i] : finalUpper[i]).toFixed(1)) });
  }
  return { line, markers };
}

const WS_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  .replace(/^http/, "ws");

// lightweight-charts v5 不支援 timezone 選項，改在前端把 unix timestamp +8h
// 讓圖表顯示台北時間（圖表以為是 UTC，實際上是 UTC+8 local time）
const TW_OFFSET = 8 * 3600;
const shiftTime = (t) => (typeof t === "number" ? t + TW_OFFSET : t);

// 圖表上餵進去的時間已經是 +8h 過的「偽 UTC」，所以這裡要用 UTC 存取子讀回正確的台北時間，
// 不能用 local getHours() 之類的（瀏覽器時區不是 UTC+8 時會算錯）。
function fmtFuturesTime(shiftedSec, intraday) {
  if (shiftedSec == null) return "—";
  const d   = new Date(shiftedSec * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  const dateStr = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  return intraday ? `${dateStr} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}` : dateStr;
}

const TIMEFRAMES = [
  { key: "D",  label: "日K" },
  { key: "60", label: "60分" },
  { key: "30", label: "30分" },
  { key: "15", label: "15分" },
  { key: "5",  label: "5分" },
  { key: "2",  label: "2分" },
  { key: "1",  label: "1分" },
];

const PRODUCTS = [
  { key: "TXF", label: "台指期（近月）" },
  { key: "TMF", label: "微型台指（近月）" },
];


const IDENTITY_LABEL = { foreign: "外資", trust: "投信", dealer: "自營商" };
const IDENTITY_COLOR = { foreign: "#38bdf8", trust: "#f59e0b", dealer: "#a78bfa" };

function QuoteHeader({ quote, loading, livePrice, priceFlash, lastClose }) {
  if (loading) return <div className="futures-quote-loading">載入中...</div>;
  if (!quote)  return null;
  const isLive       = (livePrice ?? quote.price) != null;
  // 還沒開盤成交時，優先顯示K線圖上最新一根的收盤價（實際成交過的價格），
  // 而不是 quote.prev_close——那是交易所給下一個日盤當基準用的官方參考價，
  // 跟夜盤最後成交價常常不一樣，拿來當「最後收盤」顯示反而會誤導。
  const displayPrice = isLive ? (livePrice ?? quote.price) : (lastClose ?? quote.prev_close);
  const change    = isLive && quote.prev_close ? Math.round(displayPrice - quote.prev_close) : (isLive ? quote.change : null);
  const changePct = isLive && quote.prev_close ? Math.round((displayPrice - quote.prev_close) / quote.prev_close * 10000) / 100 : (isLive ? quote.change_pct : null);
  const hasChange = change != null;
  const up = hasChange && change >= 0;
  return (
    <div className="futures-quote">
      <div className="futures-quote-main">
        <span className="futures-symbol">{quote.symbol}</span>
        <span className="futures-name">{quote.name}</span>
        <span className={`futures-price ${hasChange ? (up ? "up" : "down") : ""} ${priceFlash ? `flash-${priceFlash}` : ""}`}>
          {displayPrice != null ? displayPrice.toLocaleString() : "—"}
        </span>
        {hasChange ? (
          <span className={`futures-change ${up ? "up" : "down"}`}>
            {up ? "▲" : "▼"} {Math.abs(change)} ({up ? "+" : ""}{changePct}%)
          </span>
        ) : (
          <span className="futures-change">尚無成交（顯示最後收盤）</span>
        )}
        <span className="futures-live-dot" title="即時報價">●</span>
      </div>
      <div className="futures-quote-detail">
        <span>昨收 <b>{quote.prev_close?.toLocaleString()}</b></span>
        <span>開盤 <b>{quote.open?.toLocaleString()}</b></span>
        <span>最高 <b className="up">{quote.high?.toLocaleString()}</b></span>
        <span>最低 <b className="down">{quote.low?.toLocaleString()}</b></span>
        <span>成交量 <b>{quote.volume?.toLocaleString()}</b></span>
        {quote.bid != null && <span title="現在想賣，大約成交在這個價位">買價 <b className="down">{quote.bid.toLocaleString()}</b></span>}
        {quote.ask != null && <span title="現在想買，大約成交在這個價位">賣價 <b className="up">{quote.ask.toLocaleString()}</b></span>}
      </div>
    </div>
  );
}

const FuturesChart = forwardRef(function FuturesChart({ candles, timeframe, activeMA, showKD, showUtBot, showSuperTrend }, ref) {
  const containerRef    = useRef(null);
  const chartRef        = useRef(null);
  const candleSeriesRef = useRef(null);
  const volSeriesRef    = useRef(null);
  const lastBarRef      = useRef(null);
  const lastBarVolumeRef = useRef(0);
  const maSeriesMap     = useRef({});   // key → LineSeries
  const closesRef       = useRef([]);   // 最近 closes（滑動窗口，最大長度 max period）
  const emaStateRef     = useRef({});   // key → 上一根已確認的 EMA 值
  const dataMapRef      = useRef(new Map()); // shifted time key → OHLC/漲跌/量
  const maValueMapRef   = useRef(new Map()); // shifted time key → { maKey: value }
  const kSeriesRef      = useRef(null);
  const dSeriesRef      = useRef(null);
  const kdBarsRef        = useRef([]);   // 最近 high/low/close（滑動窗口，最後一筆＝目前這根即時值）
  const kdStateRef       = useRef({ k: 50, d: 50 }); // 上一根已確認收盤時的 K/D
  const kdValueMapRef    = useRef(new Map()); // shifted time key → { k, d }

  const [hoveredBar, setHoveredBar] = useState(null);
  const [lastBar,    setLastBar]    = useState(null);

  const MAX_PERIOD = Math.max(...MA_LINES.map(l => l.period));

  useImperativeHandle(ref, () => ({
    updateLastCandle(price, volumeDelta = 0) {
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
        lastBarVolumeRef.current = volumeDelta;
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
        lastBarVolumeRef.current += volumeDelta;
      }
      lastBarRef.current = nextBar;
      candleSeriesRef.current.update(nextBar);

      // 更新成交量柱
      if (volSeriesRef.current) {
        volSeriesRef.current.update({
          time:  nextBar.time,
          value: lastBarVolumeRef.current,
          color: nextBar.close >= nextBar.open ? "#ef4444aa" : "#22c55eaa",
        });
      }

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

      // 更新 KD：先用「舊視窗」把剛收盤的 bar 正式推進 K/D，再 push 新一根、算即時 preview
      if (kSeriesRef.current && dSeriesRef.current) {
        const bars = kdBarsRef.current;
        if (isNewBar && bars.length >= KD_PERIOD) {
          const oldWindow = bars.slice(-KD_PERIOD);
          const oldHigh = Math.max(...oldWindow.map(b => b.high));
          const oldLow  = Math.min(...oldWindow.map(b => b.low));
          const oldRsv  = oldHigh === oldLow ? 50 : (bar.close - oldLow) / (oldHigh - oldLow) * 100;
          const committedK = kdStateRef.current.k * (2 / 3) + oldRsv * (1 / 3);
          const committedD = kdStateRef.current.d * (2 / 3) + committedK * (1 / 3);
          kdStateRef.current = { k: committedK, d: committedD };
          bars.push({ high: nextBar.high, low: nextBar.low, close: nextBar.close });
          if (bars.length > KD_PERIOD + 2) kdBarsRef.current = bars.slice(-(KD_PERIOD + 2));
        } else if (bars.length) {
          bars[bars.length - 1] = { high: nextBar.high, low: nextBar.low, close: nextBar.close };
        }

        const window = kdBarsRef.current.slice(-KD_PERIOD);
        if (window.length >= KD_PERIOD) {
          const high = Math.max(...window.map(b => b.high));
          const low  = Math.min(...window.map(b => b.low));
          const rsv  = high === low ? 50 : (nextBar.close - low) / (high - low) * 100;
          const kPreview = kdStateRef.current.k * (2 / 3) + rsv * (1 / 3);
          const dPreview = kdStateRef.current.d * (2 / 3) + kPreview * (1 / 3);
          kSeriesRef.current.update({ time: nextBar.time, value: parseFloat(kPreview.toFixed(2)) });
          dSeriesRef.current.update({ time: nextBar.time, value: parseFloat(dPreview.toFixed(2)) });
        }
      }
    },
  }), [timeframe]);

  useEffect(() => {
    if (!containerRef.current || !candles.length) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current        = null;
      candleSeriesRef.current = null;
      volSeriesRef.current    = null;
      lastBarRef.current      = null;
      lastBarVolumeRef.current = 0;
      maSeriesMap.current     = {};
      kSeriesRef.current      = null;
      dSeriesRef.current      = null;
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

    candleSeriesRef.current  = candleSeries;
    volSeriesRef.current     = volSeries;
    lastBarRef.current       = candleData[candleData.length - 1] ?? null;
    lastBarVolumeRef.current = shifted.length ? (shifted[shifted.length - 1].volume ?? 0) : 0;

    // 每根K棒的 OHLC/漲跌/量，供滑鼠移到K棒上顯示資訊用
    const dataMap = new Map();
    shifted.forEach((c, i) => {
      const prev   = i > 0 ? shifted[i - 1] : null;
      const change = prev ? +(c.close - prev.close).toFixed(1) : 0;
      const chgPct = prev && prev.close ? +((change / prev.close) * 100).toFixed(2) : 0;
      dataMap.set(String(c.time), {
        time: c.time, open: c.open, high: c.high, low: c.low, close: c.close,
        volume: c.volume, change, chgPct,
      });
    });
    dataMapRef.current = dataMap;

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

    // MA / EMA 線（用 shifted 讓時間也對齊）+ maValueMap（供 hover 資訊列查值用）
    const maValueMap = new Map();
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
      lineData.forEach((item) => {
        const k = String(item.time);
        if (!maValueMap.has(k)) maValueMap.set(k, {});
        maValueMap.get(k)[key] = item.value;
      });
    });
    maValueMapRef.current = maValueMap;

    // KD（獨立子面板，不跟 K 棒共用價格軸）
    const kdValueMap = new Map();
    if (showKD) {
      const kdData = calcKD(shifted, KD_PERIOD);
      if (kdData.length) {
        const kdPane = chart.addPane();
        kdPane.setStretchFactor(0.3);
        const kSeries = kdPane.addSeries(LineSeries, {
          color: KD_K_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        });
        const dSeries = kdPane.addSeries(LineSeries, {
          color: KD_D_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        });
        kSeries.setData(kdData.map(p => ({ time: p.time, value: p.k })));
        dSeries.setData(kdData.map(p => ({ time: p.time, value: p.d })));
        kSeriesRef.current = kSeries;
        dSeriesRef.current = dSeries;
        kdData.forEach(p => kdValueMap.set(String(p.time), { k: p.k, d: p.d }));
      }
      // 即時更新用的滑動窗口／狀態：用「不含最後一根」的資料算出上一根收盤時的 K/D，
      // 讓 updateLastCandle() 對「目前這根」做即時 preview 時起點正確
      kdBarsRef.current = shifted.slice(-(KD_PERIOD + 2)).map(c => ({ high: c.high, low: c.low, close: c.close }));
      const kdBeforeLast = calcKD(shifted.slice(0, -1), KD_PERIOD);
      const lastKdState = kdBeforeLast[kdBeforeLast.length - 1];
      kdStateRef.current = lastKdState ? { k: lastKdState.k, d: lastKdState.d } : { k: 50, d: 50 };
    } else {
      kSeriesRef.current = null;
      dSeriesRef.current = null;
      kdBarsRef.current = [];
      kdStateRef.current = { k: 50, d: 50 };
    }
    kdValueMapRef.current = kdValueMap;

    // UT Bot / SuperTrend：只有日K有意義（兩者訊號都是拿日K算的），疊加停損線 + 反轉箭頭
    if (timeframe === "D") {
      const allMarkers = [];
      if (showUtBot) {
        const { line, markers } = calcUtBot(shifted);
        if (line.length) {
          const s = chart.addSeries(LineSeries, {
            color: "#f59e0b", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false,
          });
          s.setData(line);
        }
        allMarkers.push(...markers);
      }
      if (showSuperTrend) {
        const { line, markers } = calcSuperTrend(shifted);
        if (line.length) {
          const s = chart.addSeries(LineSeries, {
            color: "#a78bfa", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false,
          });
          s.setData(line);
        }
        allMarkers.push(...markers);
      }
      if (allMarkers.length) {
        allMarkers.sort((a, b) => a.time - b.time);
        createSeriesMarkers(candleSeries, allMarkers);
      }
    }

    // 無 hover 時預設顯示最後一根K棒的資訊
    const lastKey = candleData.length ? String(candleData[candleData.length - 1].time) : null;
    setLastBar(lastKey ? (dataMap.get(lastKey) ?? null) : null);
    setHoveredBar(null);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || param.point === undefined || param.point.x < 0 || param.point.y < 0) {
        setHoveredBar(null);
        return;
      }
      const key = String(param.time);
      setHoveredBar(dataMap.get(key) ?? null);
    });

    // 預設只顯示最近 45 根K棒，不然一進頁面圖會被整段歷史塞滿，還要自己縮放才看得清楚
    const DEFAULT_VISIBLE_BARS = 45;
    if (candleData.length > DEFAULT_VISIBLE_BARS) {
      chart.timeScale().setVisibleLogicalRange({
        from: candleData.length - DEFAULT_VISIBLE_BARS,
        to: candleData.length + 2,
      });
    } else {
      chart.timeScale().fitContent();
    }

    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: containerRef.current?.clientWidth || 600 });
    });
    ro.observe(containerRef.current);

    chartRef.current = chart;
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; };
  }, [candles, timeframe, activeMA, showKD, showUtBot, showSuperTrend]);

  const bar  = hoveredBar ?? lastBar;
  const clrC = bar?.change > 0 ? "#ef4444" : bar?.change < 0 ? "#22c55e" : "#94a3b8";
  const sign = (v) => v > 0 ? "+" : "";
  const activeMaEntries = MA_LINES.filter(({ key }) => activeMA[key]);
  const barMA = bar ? maValueMapRef.current.get(String(bar.time)) : null;
  const barKD = bar ? kdValueMapRef.current.get(String(bar.time)) : null;

  return (
    <div>
      <div className="chart-info-bars">
        <div className="chart-info-line">
          {bar ? (
            <>
              <span className="ci-label">時間:</span>
              <span>{fmtFuturesTime(bar.time, timeframe !== "D")}</span>
              <span className="ci-label">開:</span><span>{bar.open}</span>
              <span className="ci-label">高:</span><span>{bar.high}</span>
              <span className="ci-label">低:</span><span>{bar.low}</span>
              <span className="ci-label">收:</span>
              <span style={{ color: clrC }}>{bar.close}</span>
              <span style={{ color: clrC }}>{sign(bar.change)}{bar.change} ({sign(bar.chgPct)}{bar.chgPct}%)</span>
              <span className="ci-label">成交量:</span><span>{bar.volume?.toLocaleString() ?? "—"}</span>
            </>
          ) : <span className="ci-label">—</span>}
        </div>
        {activeMaEntries.length > 0 && (
          <div className="chart-info-line">
            {activeMaEntries.map(({ key, label, color }) =>
              barMA?.[key] != null ? (
                <span key={key} style={{ color }}>{label}: {barMA[key]}</span>
              ) : null
            )}
          </div>
        )}
        {showKD && barKD && (
          <div className="chart-info-line">
            <span style={{ color: KD_K_COLOR }}>K: {barKD.k}</span>
            <span style={{ color: KD_D_COLOR }}>D: {barKD.d}</span>
          </div>
        )}
      </div>
      <div ref={containerRef} className="futures-chart" />
    </div>
  );
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

function SignalTracking({ title, hint, data }) {
  return (
    <div>
      <h3 className="futures-section-title">{title}</h3>
      <p className="ranking-hint">{hint}</p>
      {data.length === 0 ? (
        <p className="no-data">最近 30 天沒有觸發過訊號</p>
      ) : (
        <div className="ranking-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                <th>商品</th><th>方向</th><th>觸發日</th><th>觸發價</th><th>現價</th>
                <th>至今</th><th>5日</th><th>10日</th><th>20日</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r, i) => (
                <tr key={i}>
                  <td className="col-ticker">{r.name}</td>
                  <td className={r.side === "多" ? "up" : "down"}>{r.side}</td>
                  <td>{r.trigger_date}</td>
                  <td>{r.trigger_price}</td>
                  <td>{r.price ?? "—"}</td>
                  <td className={r.since_trigger_pct > 0 ? "up" : r.since_trigger_pct < 0 ? "down" : ""}>
                    {r.since_trigger_pct != null ? `${r.since_trigger_pct > 0 ? "+" : ""}${r.since_trigger_pct}%` : "—"}
                  </td>
                  <td>{r.return_5d  != null ? `${r.return_5d  > 0 ? "+" : ""}${r.return_5d}%`  : "—"}</td>
                  <td>{r.return_10d != null ? `${r.return_10d > 0 ? "+" : ""}${r.return_10d}%` : "—"}</td>
                  <td>{r.return_20d != null ? `${r.return_20d > 0 ? "+" : ""}${r.return_20d}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const TRADE_LABEL = { buy: "買進", sell: "賣出" };
const POS_SIDE_LABEL = { long: "多", short: "空" };
const PRODUCT_LABEL_MAP = { TXF: "大台指", TMF: "微台指" };

// 邊看圖邊下單用的精簡面板：不用切去模擬下單分頁，直接對目前圖表商品下市價單。
// 智慧單、成交紀錄等完整功能還是留在模擬下單頁面，這裡只做最常用的「馬上買/賣」。
function QuickOrderPanel({ product, username, onRequireLogin, onGoFull }) {
  const [collapsed, setCollapsed]   = useState(false);
  const [side, setSide]             = useState("buy");
  const [qty, setQty]               = useState(1);
  const [account, setAccount]       = useState(null);
  const [position, setPosition]     = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError]           = useState("");
  const [msg, setMsg]               = useState("");

  const loadAccount = () => {
    if (!username) return;
    Promise.all([getFuturesPaperAccount(), getFuturesPaperPositions()])
      .then(([accRes, posRes]) => {
        setAccount(accRes.data);
        setPosition(posRes.data.positions.find(p => p.product === product) ?? null);
      })
      .catch(() => {});
  };

  useEffect(loadAccount, [username, product]);

  const handleSubmit = async () => {
    if (!username) { onRequireLogin(); return; }
    if (!qty || qty <= 0) { setError("口數需大於 0"); return; }
    setSubmitting(true);
    setError("");
    setMsg("");
    try {
      const res = await placeFuturesOrder(product, side, Number(qty));
      const d = res.data;
      const parts = [];
      if (d.closed_qty > 0) {
        parts.push(`${d.side === "buy" ? "回補空單" : "賣出多單"} ${d.closed_qty} 口` + (d.realized_pl != null ? `（損益 ${d.realized_pl.toLocaleString()}）` : ""));
      }
      if (d.opened_qty > 0) {
        parts.push(`${d.closed_qty > 0 ? "反手" : ""}${d.side === "buy" ? "做多" : "做空"} ${d.opened_qty} 口`);
      }
      setMsg(`${parts.join("，")}，成交價 ${d.price}`);
      loadAccount();
    } catch (e) {
      setError(e.response?.data?.detail || "下單失敗");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="paper-order-panel quick-order-panel">
      <div className="quick-order-header" onClick={() => setCollapsed(c => !c)}>
        <h3 className="paper-section-title">⚡ 快速下單（{PRODUCT_LABEL_MAP[product]}）</h3>
        <span className="quick-order-toggle">{collapsed ? "展開 ▾" : "收合 ▴"}</span>
      </div>

      {!collapsed && (
        !username ? (
          <p className="no-data">
            <button className="login-btn" onClick={onRequireLogin}>登入 / 註冊</button> 後即可快速下單
          </p>
        ) : (
          <>
            <div className="quick-order-status">
              {account && (
                <span>可用保證金 <b>{account.available_margin?.toLocaleString()}</b></span>
              )}
              {position ? (
                <span>目前部位 <b className={position.side === "long" ? "up" : "down"}>
                  {POS_SIDE_LABEL[position.side]} {position.qty} 口 @ {position.avg_price}
                </b></span>
              ) : (
                <span>目前無部位</span>
              )}
              {onGoFull && <button className="view-btn quick-order-full-link" onClick={onGoFull}>完整下單頁 →</button>}
            </div>

            {product !== "TMF" ? (
              <p className="no-data">大台指模擬下單暫時關閉，請切換到微台指</p>
            ) : (
              <>
                <div className="paper-side-tabs">
                  <button className={side === "buy" ? "active" : ""} onClick={() => setSide("buy")}>買</button>
                  <button className={side === "sell" ? "active" : ""} onClick={() => setSide("sell")}>賣</button>
                </div>

                <label className="paper-lots-label">
                  口數
                  <input type="number" min="1" step="1" value={qty} onChange={(e) => setQty(e.target.value)} />
                </label>

                <button className="detail-btn" onClick={handleSubmit} disabled={submitting}>
                  {submitting ? "送出中..." : `市價${TRADE_LABEL[side]}`}
                </button>

                {error && <p className="error">{error}</p>}
                {msg && <p className="paper-form-msg">{msg}</p>}
              </>
            )}
          </>
        )
      )}
    </div>
  );
}

export default function FuturesPage({ username, onRequireLogin, onNavigate }) {
  const [product,      setProduct]      = useState("TXF");
  const [timeframe,    setTimeframe]    = useState("60");
  const [quote,        setQuote]        = useState(null);
  const [candles,      setCandles]      = useState([]);
  const [institutional, setInstitutional] = useState([]);
  const [utBotSignals, setUtBotSignals]   = useState([]);
  const [supertrendSignals, setSupertrendSignals] = useState([]);
  const [quoteLoading,  setQuoteLoading]  = useState(true);
  const [candleLoading, setCandleLoading] = useState(true);
  const [livePrice,    setLivePrice]    = useState(null);
  const [priceFlash,   setPriceFlash]   = useState(null); // "up" | "down"
  const [activeMA,     setActiveMA]     = useState({ ma5: false, ma20: false, ma60: false, ema5: false, ema10: true, ema20: false, ema60: true });
  const [showKD,       setShowKD]       = useState(true);
  const [showUtBot,      setShowUtBot]      = useState(false);
  const [showSuperTrend, setShowSuperTrend] = useState(false);
  const [error, setError] = useState(null);
  const [wsKey, setWsKey] = useState(0);   // 遞增觸發 WebSocket 重連
  const wsRef        = useRef(null);
  const prevPriceRef = useRef(null);
  const chartRef     = useRef(null);

  // 初始報價（後端會依現在時間自動判斷查日盤還夜盤）
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
  // 注意：isFuturesTradingHours() 要放在 interval callback 裡面每次都重新判斷，不能只在
  // effect 掛載當下判斷一次——不然使用者若在非交易時段（如午休）就開著頁面，等到開盤時刻
  // 到了，這個 effect 不會重新執行，保底輪詢永遠不會啟動，畫面只能乾等 WebSocket。
  useEffect(() => {
    const timer = setInterval(() => {
      if (!isFuturesTradingHours()) return;
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

  // WebSocket 即時更新（wsKey 遞增觸發重連；日盤/夜盤是同一個合約 symbol，連線不分盤別）
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
        const volumeDelta = trades.reduce((s, t) => s + (t.size || 0), 0);
        const prev = prevPriceRef.current;
        setPriceFlash(prev == null ? null : price >= prev ? "up" : "down");
        setLivePrice(price);
        prevPriceRef.current = price;
        setTimeout(() => setPriceFlash(null), 400);
        chartRef.current?.updateLastCandle(price, volumeDelta);
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
    getUtBotSignals()
      .then(r => setUtBotSignals(r.data.data || []))
      .catch(() => {});
    getSupertrendSignals()
      .then(r => setSupertrendSignals(r.data.data || []))
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

      <QuoteHeader
        quote={quote} loading={quoteLoading} livePrice={livePrice} priceFlash={priceFlash}
        lastClose={candles.length ? candles[candles.length - 1].close : null}
      />

      <QuickOrderPanel
        product={product}
        username={username}
        onRequireLogin={onRequireLogin}
        onGoFull={onNavigate ? () => onNavigate("paper") : null}
      />

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
          <button
            className={`futures-ma-btn ${showKD ? "active" : ""}`}
            style={{ "--ma-color": KD_K_COLOR }}
            onClick={() => setShowKD(v => !v)}
          >
            KD
          </button>
          <button
            className={`futures-ma-btn ${showUtBot ? "active" : ""}`}
            style={{ "--ma-color": "#f59e0b" }}
            disabled={timeframe !== "D"}
            title={timeframe !== "D" ? "UT Bot 訊號僅日K可用" : ""}
            onClick={() => setShowUtBot(v => !v)}
          >
            UT Bot
          </button>
          <button
            className={`futures-ma-btn ${showSuperTrend ? "active" : ""}`}
            style={{ "--ma-color": "#a78bfa" }}
            disabled={timeframe !== "D"}
            title={timeframe !== "D" ? "SuperTrend 訊號僅日K可用" : ""}
            onClick={() => setShowSuperTrend(v => !v)}
          >
            SuperTrend
          </button>
        </div>
      </div>

      {candleLoading
        ? <div className="futures-chart-loading">K 線載入中...</div>
        : candles.length === 0 && timeframe !== "D"
          ? <div className="futures-chart-empty">盤中 K 線資料暫無（交易時段 08:45–13:45、15:00–隔日05:00）</div>
          : <FuturesChart
              ref={chartRef} candles={candles} timeframe={timeframe} activeMA={activeMA} showKD={showKD}
              showUtBot={timeframe === "D" && showUtBot} showSuperTrend={timeframe === "D" && showSuperTrend}
            />
      }

      <InstitutionalChart data={institutional} />

      <SignalTracking
        title="UT Bot 訊號追蹤"
        hint="ATR 移動停損翻轉訊號（Key Value=2、ATR 週期=11），每天收盤後檢查一次。5/10/20 個交易日報酬率會隨時間自動補上，方向欄「空」的訊號是跌才算賺。"
        data={utBotSignals}
      />

      <SignalTracking
        title="SuperTrend 訊號追蹤"
        hint="TradingView 內建標準參數（ATR 週期=10、乘數=3），每天收盤後檢查一次。5/10/20 個交易日報酬率會隨時間自動補上，方向欄「空」的訊號是跌才算賺。"
        data={supertrendSignals}
      />
    </div>
  );
}
