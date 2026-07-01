import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, LineSeries } from "lightweight-charts";

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
      // 前 period 筆 SMA 作為起始值
      ema = data.slice(0, period).reduce((s, d) => s + d.close, 0) / period;
    } else {
      ema = data[i].close * k + ema * (1 - k);
    }
    result.push({ time: data[i].date, value: parseFloat(ema.toFixed(2)) });
  }
  return result;
}

// KD 隨機指標（9日）：K = 2/3 × 前K + 1/3 × RSV，D = 2/3 × 前D + 1/3 × K
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

const KD_PANE_HEIGHT = 100;

export default function CandlestickChart({ data, period = "3mo", interval = "1d", height = 320 }) {
  const containerRef    = useRef(null);
  const chartRef        = useRef(null);
  const candleSeriesRef = useRef(null);
  const kSeriesRef      = useRef(null);
  const dSeriesRef      = useRef(null);
  const maSeriesRefs    = useRef({});
  const dataRef         = useRef([]);
  const dataIndexRef    = useRef(new Map());
  const kdMapRef        = useRef(new Map());

  const [activeMA,   setActiveMA]   = useState({ ma5: true, ma20: true, ma60: false, ma120: false, ema60: true });
  const [hoveredBar, setHoveredBar] = useState(null);
  const [hoveredKD,  setHoveredKD]  = useState(null);

  // 初始化單一 chart，含兩個 pane（K線 + KD副圖）
  useEffect(() => {
    if (!containerRef.current) return;

    const totalHeight = height + KD_PANE_HEIGHT;

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

    // pane 0 ← K 線與均線（預設 pane）
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

    // pane 1 ← KD 副圖
    const kdPane = chart.addPane();
    kSeriesRef.current = kdPane.addSeries(LineSeries, {
      color: "#f59e0b", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    dSeriesRef.current = kdPane.addSeries(LineSeries, {
      color: "#3b82f6", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });

    // 設定兩個 pane 的高度比例
    const panes = chart.panes();
    panes[0].setStretchFactor(height);
    panes[1].setStretchFactor(KD_PANE_HEIGHT);

    // crosshair → OHLC + KD 懸浮資訊
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || param.point === undefined ||
          param.point.x < 0 || param.point.y < 0) {
        setHoveredBar(null);
        setHoveredKD(null);
        return;
      }
      const candle = param.seriesData.get(candleSeriesRef.current);
      if (!candle) { setHoveredBar(null); setHoveredKD(null); return; }

      const idx = dataIndexRef.current.get(String(param.time)) ?? -1;  // key 統一用 String
      const prevClose = idx > 0 ? dataRef.current[idx - 1].close : candle.open;
      const change    = +(candle.close - prevClose).toFixed(2);
      const changePct = +((change / prevClose) * 100).toFixed(2);
      setHoveredBar({ ...candle, change, changePct });
      setHoveredKD(kdMapRef.current.get(String(param.time)) ?? null);
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

  // 資料更新
  useEffect(() => {
    if (!candleSeriesRef.current || !data?.length) return;

    dataRef.current = data;
    const indexMap = new Map();
    data.forEach((d, i) => indexMap.set(String(d.date), i));
    dataIndexRef.current = indexMap;

    // 60m 為 unix timestamp（數字），其他為日期字串
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

    const { kArr, dArr } = calcKD(data);
    kSeriesRef.current?.setData(kArr);
    dSeriesRef.current?.setData(dArr);

    const kdMap = new Map();
    kArr.forEach((item, i) => kdMap.set(item.time, { k: item.value, d: dArr[i].value }));
    kdMapRef.current = kdMap;

    applyVisibleRange(period);
  }, [data]);

  useEffect(() => { applyVisibleRange(period); }, [period]);

  useEffect(() => {
    MA_CONFIG.forEach(({ key }) => {
      maSeriesRefs.current[key]?.applyOptions({ visible: activeMA[key] });
    });
  }, [activeMA]);

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
        {/* KD 標籤浮在副圖左上角 */}
        <div className="kd-label-bar" style={{ bottom: KD_PANE_HEIGHT - 2 }}>
          <span className="kd-label-title">KD(9)</span>
          <span className="kd-k-val">K: {hoveredKD ? hoveredKD.k.toFixed(2) : "—"}</span>
          <span className="kd-d-val">D: {hoveredKD ? hoveredKD.d.toFixed(2) : "—"}</span>
        </div>
      </div>
    </div>
  );
}
