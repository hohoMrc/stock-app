import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, LineSeries, HistogramSeries } from "lightweight-charts";

const MA_CONFIG = [
  { key: "ma5",   period: 5,   label: "MA5",   color: "#f59e0b" },
  { key: "ma20",  period: 20,  label: "MA20",  color: "#3b82f6" },
  { key: "ma60",  period: 60,  label: "MA60",  color: "#8b5cf6" },
  { key: "ma120", period: 120, label: "MA120", color: "#ec4899" },
  { key: "ema60", period: 60,  label: "EMA60", color: "#10b981", ema: true },
];

function calcMA(data, period) {
  const result = [];
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    const avg = slice.reduce((sum, d) => sum + d.close, 0) / period;
    result.push({ time: data[i].date, value: parseFloat(avg.toFixed(2)) });
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
    result.push({ time: data[i].date, value: parseFloat(ema.toFixed(2)) });
  }
  return result;
}

function calcKD(data, period = 9) {
  const kArr = [];
  const dArr = [];
  let prevK = 50;
  let prevD = 50;
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) continue;
    const slice = data.slice(i - period + 1, i + 1);
    const lowest  = Math.min(...slice.map((d) => d.low));
    const highest = Math.max(...slice.map((d) => d.high));
    const rsv = highest === lowest ? 50 : ((data[i].close - lowest) / (highest - lowest)) * 100;
    prevK = (2 / 3) * prevK + (1 / 3) * rsv;
    prevD = (2 / 3) * prevD + (1 / 3) * prevK;
    kArr.push({ time: data[i].date, value: parseFloat(prevK.toFixed(2)) });
    dArr.push({ time: data[i].date, value: parseFloat(prevD.toFixed(2)) });
  }
  return { kArr, dArr };
}

function calcBOLL(data, period = 20, mult = 2) {
  const upper = [], mid = [], lower = [];
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    const mean = slice.reduce((s, d) => s + d.close, 0) / period;
    const std = Math.sqrt(slice.reduce((s, d) => s + (d.close - mean) ** 2, 0) / period);
    upper.push({ time: data[i].date, value: parseFloat((mean + mult * std).toFixed(2)) });
    mid.push({ time: data[i].date, value: parseFloat(mean.toFixed(2)) });
    lower.push({ time: data[i].date, value: parseFloat((mean - mult * std).toFixed(2)) });
  }
  return { upper, mid, lower };
}

function calcEMAArray(closes, period) {
  const k = 2 / (period + 1);
  const result = new Array(closes.length).fill(null);
  let ema = null;
  for (let i = 0; i < closes.length; i++) {
    if (ema === null) {
      if (i < period - 1) continue;
      ema = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
    } else {
      ema = closes[i] * k + ema * (1 - k);
    }
    result[i] = ema;
  }
  return result;
}

function calcMACD(data, fast = 12, slow = 26, signal = 9) {
  const closes = data.map((d) => d.close);
  const ema12 = calcEMAArray(closes, fast);
  const ema26 = calcEMAArray(closes, slow);

  const dif = new Array(data.length).fill(null);
  for (let i = 0; i < data.length; i++) {
    if (ema12[i] !== null && ema26[i] !== null) dif[i] = ema12[i] - ema26[i];
  }

  const dea = new Array(data.length).fill(null);
  const sk = 2 / (signal + 1);
  let deaEma = null;
  let cnt = 0;
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    if (dif[i] === null) continue;
    cnt++;
    sum += dif[i];
    if (deaEma === null) {
      if (cnt < signal) continue;
      deaEma = sum / signal;
    } else {
      deaEma = dif[i] * sk + deaEma * (1 - sk);
    }
    dea[i] = deaEma;
  }

  const difArr = [], deaArr = [], histArr = [];
  for (let i = 0; i < data.length; i++) {
    if (dif[i] === null) continue;
    difArr.push({ time: data[i].date, value: parseFloat(dif[i].toFixed(4)) });
    if (dea[i] !== null) {
      deaArr.push({ time: data[i].date, value: parseFloat(dea[i].toFixed(4)) });
      const h = (dif[i] - dea[i]) * 2;
      histArr.push({
        time: data[i].date,
        value: parseFloat(h.toFixed(4)),
        color: h >= 0 ? "rgba(220,38,38,0.65)" : "rgba(22,163,74,0.65)",
      });
    }
  }
  return { difArr, deaArr, histArr };
}

const PERIOD_DAYS = {
  "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825,
};

function getFromDate(period, asUnix = false) {
  const days = PERIOD_DAYS[period] ?? 90;
  const d = new Date();
  d.setDate(d.getDate() - days);
  if (asUnix) return Math.floor(d.getTime() / 1000);
  return d.toISOString().slice(0, 10);
}

const KD_PANE_HEIGHT   = 80;
const MACD_PANE_HEIGHT = 80;

export default function CandlestickChart({ data, period = "3mo", interval = "1d", height = 320 }) {
  const containerRef    = useRef(null);
  const chartRef        = useRef(null);
  const candleSeriesRef = useRef(null);
  const kSeriesRef      = useRef(null);
  const dSeriesRef      = useRef(null);
  const maSeriesRefs    = useRef({});
  const bollUpperRef    = useRef(null);
  const bollMidRef      = useRef(null);
  const bollLowerRef    = useRef(null);
  const difSeriesRef    = useRef(null);
  const deaSeriesRef    = useRef(null);
  const macdHistRef     = useRef(null);
  const dataRef         = useRef([]);
  const dataIndexRef    = useRef(new Map());
  const kdMapRef        = useRef(new Map());
  const macdMapRef      = useRef(new Map());

  const [activeMA,    setActiveMA]    = useState({ ma5: true, ma20: true, ma60: false, ma120: false, ema60: true });
  const [showBOLL,    setShowBOLL]    = useState(false);
  const [hoveredBar,  setHoveredBar]  = useState(null);
  const [hoveredKD,   setHoveredKD]   = useState(null);
  const [hoveredMACD, setHoveredMACD] = useState(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const totalHeight = height + KD_PANE_HEIGHT + MACD_PANE_HEIGHT;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: totalHeight,
      layout: { background: { color: "#111827" }, textColor: "#7a94b0" },
      grid:   { vertLines: { color: "#1a2235" }, horzLines: { color: "#1a2235" } },
      rightPriceScale: { borderColor: "#1e3a5f" },
      timeScale: { borderColor: "#1e3a5f", timeVisible: false },
      crosshair: {
        vertLine: { color: "rgba(6,182,212,0.4)", style: 0 },
        horzLine: { color: "rgba(6,182,212,0.4)", style: 0 },
      },
      localization: { dateFormat: "yyyy/MM/dd" },
    });
    chartRef.current = chart;

    // pane 0: K 線 + MA + BOLL
    candleSeriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: "#dc2626", downColor: "#16a34a",
      borderUpColor: "#dc2626", borderDownColor: "#16a34a",
      wickUpColor:   "#dc2626", wickDownColor:   "#16a34a",
    });

    MA_CONFIG.forEach(({ key, color }) => {
      maSeriesRefs.current[key] = chart.addSeries(LineSeries, {
        color, lineWidth: 1.5,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      });
    });

    const bollOpts = {
      lineWidth: 1, lineStyle: 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      visible: false,
    };
    bollUpperRef.current = chart.addSeries(LineSeries, { ...bollOpts, color: "#7c3aed" });
    bollMidRef.current   = chart.addSeries(LineSeries, { ...bollOpts, color: "#a78bfa", lineStyle: 0 });
    bollLowerRef.current = chart.addSeries(LineSeries, { ...bollOpts, color: "#7c3aed" });

    // pane 1: KD
    const kdPane = chart.addPane();
    kSeriesRef.current = kdPane.addSeries(LineSeries, {
      color: "#f59e0b", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    dSeriesRef.current = kdPane.addSeries(LineSeries, {
      color: "#3b82f6", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });

    // pane 2: MACD
    const macdPane = chart.addPane();
    macdHistRef.current = macdPane.addSeries(HistogramSeries, {
      priceLineVisible: false, lastValueVisible: false,
    });
    difSeriesRef.current = macdPane.addSeries(LineSeries, {
      color: "#fbbf24", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    deaSeriesRef.current = macdPane.addSeries(LineSeries, {
      color: "#60a5fa", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });

    const panes = chart.panes();
    panes[0].setStretchFactor(height);
    panes[1].setStretchFactor(KD_PANE_HEIGHT);
    panes[2].setStretchFactor(MACD_PANE_HEIGHT);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || param.point === undefined ||
          param.point.x < 0 || param.point.y < 0) {
        setHoveredBar(null); setHoveredKD(null); setHoveredMACD(null);
        return;
      }
      const candle = param.seriesData.get(candleSeriesRef.current);
      if (!candle) { setHoveredBar(null); setHoveredKD(null); setHoveredMACD(null); return; }

      const key = String(param.time);
      const idx = dataIndexRef.current.get(key) ?? -1;
      const prevClose = idx > 0 ? dataRef.current[idx - 1].close : candle.open;
      const change    = +(candle.close - prevClose).toFixed(2);
      const changePct = +((change / prevClose) * 100).toFixed(2);
      setHoveredBar({ ...candle, change, changePct });
      setHoveredKD(kdMapRef.current.get(key) ?? null);
      setHoveredMACD(macdMapRef.current.get(key) ?? null);
    });

    const handleResize = () => {
      if (chartRef.current && containerRef.current)
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chartRef.current?.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      kSeriesRef.current = null;
      dSeriesRef.current = null;
      bollUpperRef.current = null;
      bollMidRef.current = null;
      bollLowerRef.current = null;
      difSeriesRef.current = null;
      deaSeriesRef.current = null;
      macdHistRef.current = null;
      maSeriesRefs.current = {};
    };
  }, [height]);

  function applyVisibleRange(p) {
    if (!chartRef.current || !data?.length) return;
    const isUnix = typeof data[0]?.date === "number";
    const from = getFromDate(p, isUnix);
    const to   = data[data.length - 1]?.date;
    if (from && to) chartRef.current.timeScale().setVisibleRange({ from, to });
  }

  useEffect(() => {
    if (!candleSeriesRef.current || !data?.length) return;

    dataRef.current = data;
    const indexMap = new Map();
    data.forEach((d, i) => indexMap.set(String(d.date), i));
    dataIndexRef.current = indexMap;

    const isUnix = typeof data[0]?.date === "number";
    if (chartRef.current) {
      chartRef.current.applyOptions({
        timeScale: { borderColor: "#1e3a5f", timeVisible: isUnix },
      });
    }

    candleSeriesRef.current.setData(
      data.map((d) => ({ time: d.date, open: d.open, high: d.high, low: d.low, close: d.close }))
    );

    MA_CONFIG.forEach(({ key, period: maPeriod, ema }) => {
      const fn = ema ? calcEMA : calcMA;
      maSeriesRefs.current[key]?.setData(fn(data, maPeriod));
    });

    // BOLL
    const { upper, mid, lower } = calcBOLL(data);
    bollUpperRef.current?.setData(upper);
    bollMidRef.current?.setData(mid);
    bollLowerRef.current?.setData(lower);

    // KD
    const { kArr, dArr } = calcKD(data);
    kSeriesRef.current?.setData(kArr);
    dSeriesRef.current?.setData(dArr);
    const kdMap = new Map();
    kArr.forEach((item, i) => kdMap.set(String(item.time), { k: item.value, d: dArr[i]?.value }));
    kdMapRef.current = kdMap;

    // MACD
    const { difArr, deaArr, histArr } = calcMACD(data);
    difSeriesRef.current?.setData(difArr);
    deaSeriesRef.current?.setData(deaArr);
    macdHistRef.current?.setData(histArr);
    const macdMap = new Map();
    histArr.forEach((item, i) => {
      macdMap.set(String(item.time), {
        dif: difArr.find((d) => String(d.time) === String(item.time))?.value,
        dea: deaArr[i]?.value,
        hist: item.value,
      });
    });
    macdMapRef.current = macdMap;

    applyVisibleRange(period);
  }, [data]);

  useEffect(() => { applyVisibleRange(period); }, [period]);

  useEffect(() => {
    MA_CONFIG.forEach(({ key }) => {
      maSeriesRefs.current[key]?.applyOptions({ visible: activeMA[key] });
    });
  }, [activeMA]);

  useEffect(() => {
    const v = showBOLL;
    bollUpperRef.current?.applyOptions({ visible: v });
    bollMidRef.current?.applyOptions({ visible: v });
    bollLowerRef.current?.applyOptions({ visible: v });
  }, [showBOLL]);

  const toggleMA = (key) => setActiveMA((prev) => ({ ...prev, [key]: !prev[key] }));

  const sign = (v) => (v > 0 ? "+" : "");
  const changeColor = hoveredBar
    ? hoveredBar.change > 0 ? "#dc2626" : hoveredBar.change < 0 ? "#16a34a" : "#64748b"
    : undefined;

  return (
    <div style={{ position: "relative" }}>
      <div className="ma-toggle-bar">
        {MA_CONFIG.map(({ key, label, color }) => (
          <button
            key={key}
            className={`ma-toggle-btn ${activeMA[key] ? "active" : ""}`}
            style={{ "--ma-color": color }}
            onClick={() => toggleMA(key)}
          >
            <span className="ma-dot" />
            {label}
          </button>
        ))}
        <button
          className={`ma-toggle-btn ${showBOLL ? "active" : ""}`}
          style={{ "--ma-color": "#7c3aed" }}
          onClick={() => setShowBOLL((v) => !v)}
        >
          <span className="ma-dot" />
          BOLL
        </button>
      </div>

      <div className="ohlc-bar" style={{ opacity: hoveredBar ? 1 : 0 }}>
        {hoveredBar && (
          <>
            <span className="ohlc-item"><span className="ohlc-label">開</span>{hoveredBar.open}</span>
            <span className="ohlc-item"><span className="ohlc-label">高</span>{hoveredBar.high}</span>
            <span className="ohlc-item"><span className="ohlc-label">低</span>{hoveredBar.low}</span>
            <span className="ohlc-item"><span className="ohlc-label">收</span>{hoveredBar.close}</span>
            <span className="ohlc-item" style={{ color: changeColor }}>
              {sign(hoveredBar.change)}{hoveredBar.change}
            </span>
            <span className="ohlc-item" style={{ color: changeColor }}>
              ({sign(hoveredBar.changePct)}{hoveredBar.changePct}%)
            </span>
          </>
        )}
      </div>

      <div ref={containerRef} style={{ width: "100%", position: "relative" }}>
        {/* KD 標籤 */}
        <div className="kd-label-bar" style={{ bottom: KD_PANE_HEIGHT + MACD_PANE_HEIGHT - 2 }}>
          <span className="kd-label-title">KD(9)</span>
          <span className="kd-k-val">K: {hoveredKD ? hoveredKD.k.toFixed(2) : "—"}</span>
          <span className="kd-d-val">D: {hoveredKD ? hoveredKD.d?.toFixed(2) : "—"}</span>
        </div>
        {/* MACD 標籤 */}
        <div className="kd-label-bar" style={{ bottom: MACD_PANE_HEIGHT - 2 }}>
          <span className="kd-label-title">MACD(12,26,9)</span>
          <span style={{ color: "#fbbf24" }}>DIF: {hoveredMACD ? hoveredMACD.dif?.toFixed(2) : "—"}</span>
          <span style={{ color: "#60a5fa" }}>DEA: {hoveredMACD ? hoveredMACD.dea?.toFixed(2) : "—"}</span>
          <span style={{ color: hoveredMACD?.hist >= 0 ? "#dc2626" : "#16a34a" }}>
            MACD: {hoveredMACD ? hoveredMACD.hist?.toFixed(2) : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}
