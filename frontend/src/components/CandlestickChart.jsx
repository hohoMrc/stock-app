import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, LineSeries } from "lightweight-charts";

const MA_CONFIG = [
  { key: "ma5",   period: 5,   label: "MA5",   color: "#f59e0b" },
  { key: "ma20",  period: 20,  label: "MA20",  color: "#3b82f6" },
  { key: "ma60",  period: 60,  label: "MA60",  color: "#8b5cf6" },
  { key: "ma120", period: 120, label: "MA120", color: "#ec4899" },
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

const PERIOD_DAYS = {
  "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825,
};

function getFromDate(period) {
  const days = PERIOD_DAYS[period] ?? 90;
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function CandlestickChart({ data, period = "3mo", height = 320 }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const maSeriesRefs = useRef({});
  const dataRef = useRef([]);           // 供 crosshair callback 查前一根收盤價
  const dataIndexRef = useRef(new Map());
  const [activeMA, setActiveMA] = useState({ ma5: true, ma20: true, ma60: false, ma120: false });
  const [hoveredBar, setHoveredBar] = useState(null);

  // 初始化圖表
  useEffect(() => {
    if (!containerRef.current) return;

    chartRef.current = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: "#111827" },
        textColor: "#7a94b0",
      },
      grid: {
        vertLines: { color: "#1a2235" },
        horzLines: { color: "#1a2235" },
      },
      rightPriceScale: { borderColor: "#1e3a5f" },
      timeScale: { borderColor: "#1e3a5f", timeVisible: false },
      crosshair: {
        vertLine: { color: "rgba(6,182,212,0.4)", style: 0 },
        horzLine: { color: "rgba(6,182,212,0.4)", style: 0 },
      },
      localization: {
        dateFormat: "yyyy/MM/dd",
      },
    });

    candleSeriesRef.current = chartRef.current.addSeries(CandlestickSeries, {
      upColor: "#dc2626",
      downColor: "#16a34a",
      borderUpColor: "#dc2626",
      borderDownColor: "#16a34a",
      wickUpColor: "#dc2626",
      wickDownColor: "#16a34a",
    });

    // 建立所有 MA 線系列
    MA_CONFIG.forEach(({ key, color }) => {
      maSeriesRefs.current[key] = chartRef.current.addSeries(LineSeries, {
        color,
        lineWidth: 1.5,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    });

    // crosshair 移動時顯示 OHLC + 漲跌
    chartRef.current.subscribeCrosshairMove((param) => {
      if (!param.time || param.point === undefined ||
          param.point.x < 0 || param.point.y < 0) {
        setHoveredBar(null);
        return;
      }
      const candle = param.seriesData.get(candleSeriesRef.current);
      if (!candle) { setHoveredBar(null); return; }

      const idx = dataIndexRef.current.get(String(param.time)) ?? -1;
      const prevClose = idx > 0 ? dataRef.current[idx - 1].close : candle.open;
      const change = +(candle.close - prevClose).toFixed(2);
      const changePct = +((change / prevClose) * 100).toFixed(2);

      setHoveredBar({ ...candle, change, changePct });
    });

    const handleResize = () => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chartRef.current?.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      maSeriesRefs.current = {};
    };
  }, [height]);

  function applyVisibleRange(p) {
    if (!chartRef.current || !data?.length) return;
    const from = getFromDate(p);
    const to = data[data.length - 1]?.date;
    if (from && to) chartRef.current.timeScale().setVisibleRange({ from, to });
  }

  // 資料更新時重算均線並套用可見範圍
  useEffect(() => {
    if (!candleSeriesRef.current || !data?.length) return;

    // 建立 date → index 查找表，供 crosshair 計算漲跌
    dataRef.current = data;
    const indexMap = new Map();
    data.forEach((d, i) => indexMap.set(d.date, i));
    dataIndexRef.current = indexMap;

    candleSeriesRef.current.setData(
      data.map((d) => ({ time: d.date, open: d.open, high: d.high, low: d.low, close: d.close }))
    );

    MA_CONFIG.forEach(({ key, period: maPeriod }) => {
      const maData = calcMA(data, maPeriod);
      maSeriesRefs.current[key]?.setData(maData);
    });

    applyVisibleRange(period);
  }, [data]);

  // 切換 period 時只調整可見範圍，不重抓資料
  useEffect(() => {
    applyVisibleRange(period);
  }, [period]);

  // 切換顯示/隱藏均線
  useEffect(() => {
    MA_CONFIG.forEach(({ key }) => {
      const series = maSeriesRefs.current[key];
      if (!series) return;
      series.applyOptions({ visible: activeMA[key] });
    });
  }, [activeMA]);

  const toggleMA = (key) => {
    setActiveMA((prev) => ({ ...prev, [key]: !prev[key] }));
  };

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

      {/* OHLC 懸浮資訊列 */}
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

      <div ref={containerRef} style={{ width: "100%" }} />
    </div>
  );
}
