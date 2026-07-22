import { useEffect, useRef, useState, useCallback } from "react";
import { createChart, CandlestickSeries, LineSeries, HistogramSeries } from "lightweight-charts";

const MA_CONFIG = [
  { key: "ma5",   period: 5,  label: "MA5",   color: "#f59e0b" },
  { key: "ma10",  period: 10, label: "MA10",  color: "#38bdf8" },
  { key: "ma20",  period: 20, label: "MA20",  color: "#facc15" },
  { key: "ma30",  period: 30, label: "MA30",  color: "#a78bfa" },
  { key: "ma60",  period: 60, label: "MA60",  color: "#34d399" },
  { key: "ema10", period: 10, label: "EMA10", color: "#fb923c", ema: true },
  { key: "ema60", period: 60, label: "EMA60", color: "#ef4444", ema: true },
];

function calcMA(data, period) {
  const result = [];
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    const avg = slice.reduce((s, d) => s + d.close, 0) / period;
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

function calcBOLL(data, period = 20, mult = 2) {
  const upper = [], mid = [], lower = [];
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    const mean = slice.reduce((s, d) => s + d.close, 0) / period;
    const std  = Math.sqrt(slice.reduce((s, d) => s + (d.close - mean) ** 2, 0) / period);
    upper.push({ time: data[i].date, value: parseFloat((mean + mult * std).toFixed(2)) });
    mid.push(  { time: data[i].date, value: parseFloat(mean.toFixed(2)) });
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
  const ema12  = calcEMAArray(closes, fast);
  const ema26  = calcEMAArray(closes, slow);
  const dif    = new Array(data.length).fill(null);
  for (let i = 0; i < data.length; i++) {
    if (ema12[i] !== null && ema26[i] !== null) dif[i] = ema12[i] - ema26[i];
  }
  const dea = new Array(data.length).fill(null);
  const sk  = 2 / (signal + 1);
  let deaEma = null, cnt = 0, sum = 0;
  for (let i = 0; i < data.length; i++) {
    if (dif[i] === null) continue;
    cnt++; sum += dif[i];
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
        time:  data[i].date,
        value: parseFloat(h.toFixed(4)),
        color: h >= 0 ? "rgba(220,38,38,0.65)" : "rgba(22,163,74,0.65)",
      });
    }
  }
  return { difArr, deaArr, histArr };
}

function calcKD(data, n = 9) {
  const kArr = [], dArr = [];
  let prevK = 50, prevD = 50;
  for (let i = 0; i < data.length; i++) {
    const slice = data.slice(Math.max(0, i - n + 1), i + 1);
    const low   = Math.min(...slice.map((d) => d.low));
    const high  = Math.max(...slice.map((d) => d.high));
    const rsv   = high === low ? 50 : ((data[i].close - low) / (high - low)) * 100;
    const k = (2 / 3) * prevK + (1 / 3) * rsv;
    const d = (2 / 3) * prevD + (1 / 3) * k;
    kArr.push({ time: data[i].date, value: parseFloat(k.toFixed(2)) });
    dArr.push({ time: data[i].date, value: parseFloat(d.toFixed(2)) });
    prevK = k; prevD = d;
  }
  return { kArr, dArr };
}

function calcVolMA(data, period) {
  const result = [];
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    const avg   = slice.reduce((s, d) => s + Math.round((d.volume || 0) / 1000), 0) / period;
    result.push({ time: data[i].date, value: Math.round(avg) });
  }
  return result;
}

function fmtVol(v) {
  if (v == null) return "—";
  if (v >= 10_000) return `${(v / 10_000).toFixed(1)}萬`;
  if (v >= 1_000)  return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

function fmtTime(t, isUnix) {
  if (t == null) return "—";
  if (isUnix && typeof t === "number") {
    const d   = new Date(t * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  return String(t);
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

const VOL_PANE_HEIGHT  = 80;
const MACD_PANE_HEIGHT = 100;
const KD_PANE_HEIGHT   = 100;

const DEFAULT_ACTIVE_MA = { ma5: false, ma10: false, ma20: false, ma30: false, ma60: false, ema10: true, ema60: true };

export default function CandlestickChart({ data, period = "3mo", interval = "1d", height = 320, defaultMA = null, showMACD = true }) {
  const containerRef    = useRef(null);
  const chartRef        = useRef(null);
  const candleSeriesRef = useRef(null);
  const maSeriesRefs    = useRef({});
  const bollUpperRef    = useRef(null);
  const bollMidRef      = useRef(null);
  const bollLowerRef    = useRef(null);
  const volSeriesRef    = useRef(null);
  const volMa5Ref       = useRef(null);
  const volMa10Ref      = useRef(null);
  const volMa20Ref      = useRef(null);
  const difSeriesRef    = useRef(null);
  const deaSeriesRef    = useRef(null);
  const macdHistRef     = useRef(null);
  const kSeriesRef      = useRef(null);
  const dSeriesRef      = useRef(null);
  const dataRef         = useRef([]);
  const dataIndexRef    = useRef(new Map());
  const lastWidthRef    = useRef(0);
  const maMapRef        = useRef(new Map());
  const bollMapRef      = useRef(new Map());
  const volMapRef       = useRef(new Map());
  const macdMapRef      = useRef(new Map());
  const kdMapRef        = useRef(new Map());

  const [activeMA,    setActiveMA]    = useState(() => defaultMA ?? DEFAULT_ACTIVE_MA);
  const [showBOLL,    setShowBOLL]    = useState(false);
  const [hoveredBar,  setHoveredBar]  = useState(null);
  const [hoveredMACD, setHoveredMACD] = useState(null);
  const [hoveredKD,   setHoveredKD]   = useState(null);
  const [lastBar,     setLastBar]     = useState(null);
  const [lastMACD,    setLastMACD]    = useState(null);
  const [lastKD,      setLastKD]      = useState(null);

  // 動態 label top 定位（pane 被拖動時更新）
  const [volTop,  setVolTop]  = useState(0);
  const [macdTop, setMacdTop] = useState(0);
  const [kdTop,   setKdTop]   = useState(0);
  const paneRORef = useRef(null);

  const syncLabelOffsets = useCallback(() => {
    const panes = chartRef.current?.panes();
    const expectedPanes = showMACD ? 4 : 3;
    if (!panes || panes.length < expectedPanes || !containerRef.current) return;
    const totalH = containerRef.current.clientHeight;
    if (!totalH) return;
    const f = panes.map(p => (typeof p.getStretchFactor === "function" ? p.getStretchFactor() : 80));
    const sum = f.reduce((a, b) => a + b, 0);
    if (!sum) return;
    const kH    = Math.round((f[0] / sum) * totalH);
    const volH  = Math.round((f[1] / sum) * totalH);
    setVolTop(kH - 20);
    if (showMACD) {
      const macdH = Math.round((f[2] / sum) * totalH);
      setMacdTop(kH + volH + 2);
      setKdTop(kH + volH + macdH + 2);
    } else {
      setKdTop(kH + volH + 2);
    }
  }, [showMACD]);

  // ── 建立圖表實例 ──────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    const subPaneHeight = VOL_PANE_HEIGHT + (showMACD ? MACD_PANE_HEIGHT : 0) + KD_PANE_HEIGHT;
    const totalHeight = containerRef.current.clientHeight || (subPaneHeight + 320);
    const kLineH = Math.max(120, totalHeight - subPaneHeight);
    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height: totalHeight,
      // panes.enableResize: false — 各子圖高度已用 setStretchFactor 固定好，
      // 不需要讓使用者手動拖曳分隔線調整（手機上容易誤觸），分隔線顏色也融入背景避免擋到文字。
      layout: {
        background: { color: "#111827" },
        textColor: "#7a94b0",
        panes: { enableResize: false, separatorColor: "#111827" },
      },
      grid:   { vertLines: { color: "#1a2235" }, horzLines: { color: "#1a2235" } },
      rightPriceScale: { borderColor: "#1e3a5f", autoScale: true },
      // fixRightEdge：最新一根K棒已經在最右邊時，不能再往右滑出空白區域，滑到底就是底。
      timeScale:       { borderColor: "#1e3a5f", timeVisible: false, fixRightEdge: true, rightOffset: 0 },
      crosshair: {
        vertLine: { color: "rgba(6,182,212,0.4)", style: 0 },
        horzLine: { color: "rgba(6,182,212,0.4)", style: 0 },
      },
      // 價格軸（右側刻度）不給手動拖曳縮放，固定自動依可視範圍內的K棒縮放，
      // 不然手指划到價格軸容易不小心拖動、要再手動拉回正確比例才看得到完整K棒。
      // 整張圖固定一次顯示約50根K棒（見 applyVisibleRange），所以也關掉滾輪/雙指縮放，
      // 不讓使用者手動放大縮小改變顯示根數，只保留左右拖曳平移看更早/更新的K棒。
      handleScale: { axisPressedMouseMove: { time: true, price: false }, mouseWheel: false, pinch: false },
      localization: { dateFormat: "yyyy/MM/dd" },
    });
    chartRef.current = chart;

    // pane 0: K 線 + MA + BOLL
    candleSeriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor:        "#dc2626", downColor:        "#16a34a",
      borderUpColor:  "#dc2626", borderDownColor:  "#16a34a",
      wickUpColor:    "#dc2626", wickDownColor:    "#16a34a",
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

    // pane 1: 量能
    const volPane = chart.addPane();
    volSeriesRef.current = volPane.addSeries(HistogramSeries, {
      priceLineVisible: false, lastValueVisible: false,
      priceFormat: {
        type: "custom",
        formatter: (v) => {
          if (v >= 10000) return `${(v / 10000).toFixed(1)}萬`;
          if (v >= 1000)  return `${(v / 1000).toFixed(0)}K`;
          return String(Math.round(v));
        },
      },
    });
    volMa5Ref.current  = volPane.addSeries(LineSeries, {
      color: "#f59e0b", lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    volMa10Ref.current = volPane.addSeries(LineSeries, {
      color: "#38bdf8", lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    volMa20Ref.current = volPane.addSeries(LineSeries, {
      color: "#f97316", lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });

    // pane 2: MACD（可選）— 三個系列強制同一 price scale，確保 0 軸在可視範圍
    if (showMACD) {
      const macdPane = chart.addPane();
      macdHistRef.current = macdPane.addSeries(HistogramSeries, {
        priceLineVisible: false, lastValueVisible: false,
        priceScaleId: 'right',
      });
      difSeriesRef.current = macdPane.addSeries(LineSeries, {
        color: "#fbbf24", lineWidth: 1.5,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        priceScaleId: 'right',
      });
      deaSeriesRef.current = macdPane.addSeries(LineSeries, {
        color: "#60a5fa", lineWidth: 1.5,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        priceScaleId: 'right',
      });
    }

    // pane 3（或 2，若無 MACD）: KD (Stochastic 9)
    const kdPane = chart.addPane();
    kSeriesRef.current = kdPane.addSeries(LineSeries, {
      color: "#f59e0b", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    dSeriesRef.current = kdPane.addSeries(LineSeries, {
      color: "#3b82f6", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });

    const panes = chart.panes();
    panes[0].setStretchFactor(kLineH);
    panes[1].setStretchFactor(VOL_PANE_HEIGHT);
    let paneIdx = 2;
    if (showMACD) { panes[paneIdx].setStretchFactor(MACD_PANE_HEIGHT); paneIdx++; }
    panes[paneIdx].setStretchFactor(KD_PANE_HEIGHT);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || param.point === undefined ||
          param.point.x < 0 || param.point.y < 0) {
        setHoveredBar(null); setHoveredMACD(null); setHoveredKD(null);
        return;
      }
      const candle = param.seriesData.get(candleSeriesRef.current);
      if (!candle) { setHoveredBar(null); setHoveredMACD(null); setHoveredKD(null); return; }

      const key     = String(param.time);
      const idx     = dataIndexRef.current.get(key) ?? -1;
      const prev    = idx > 0 ? dataRef.current[idx - 1] : null;
      const change  = prev ? +(candle.close - prev.close).toFixed(2) : 0;
      const chgPct  = prev ? +((change / prev.close) * 100).toFixed(2) : 0;
      setHoveredBar({
        ...candle, change, chgPct,
        ma:    maMapRef.current.get(key),
        boll:  bollMapRef.current.get(key),
        volMa: volMapRef.current.get(key),
      });
      setHoveredMACD(macdMapRef.current.get(key) ?? null);
      setHoveredKD(kdMapRef.current.get(key) ?? null);
    });

    const ro = new ResizeObserver(([entry]) => {
      if (!chartRef.current) return;
      const newW = entry.contentRect.width;
      const newH = entry.contentRect.height || totalHeight;
      const hadNoWidth = lastWidthRef.current === 0;
      chartRef.current.applyOptions({ width: newW, height: newH });
      const newKH = Math.max(120, newH - subPaneHeight);
      chartRef.current.panes()[0]?.setStretchFactor(newKH);
      syncLabelOffsets();
      // 手機版分頁隱藏中的圖表容器寬度是 0，這時候套用的可視範圍不會正確依寬度縮放K棒間距；
      // 等分頁被切到看得見、寬度變成非 0 的那一刻，要重新套用一次才會正確撐開填滿寬度。
      if (hadNoWidth && newW > 0) applyVisibleRange(period);
      lastWidthRef.current = newW;
    });
    ro.observe(containerRef.current);

    // 監聽 pane canvas 高度變化（pane 分隔線拖動時更新 label 位置）
    syncLabelOffsets();
    if (paneRORef.current) paneRORef.current.disconnect();
    paneRORef.current = new ResizeObserver(syncLabelOffsets);
    containerRef.current.querySelectorAll("canvas").forEach(c => paneRORef.current.observe(c));

    return () => {
      ro.disconnect();
      paneRORef.current?.disconnect();
      chartRef.current?.remove();
      chartRef.current        = null;
      candleSeriesRef.current = null;
      bollUpperRef.current    = null;
      bollMidRef.current      = null;
      bollLowerRef.current    = null;
      volSeriesRef.current    = null;
      volMa5Ref.current       = null;
      volMa10Ref.current      = null;
      volMa20Ref.current      = null;
      difSeriesRef.current    = null;
      deaSeriesRef.current    = null;
      macdHistRef.current     = null;
      kSeriesRef.current      = null;
      dSeriesRef.current      = null;
      maSeriesRefs.current    = {};
    };
  }, [showMACD]);

  // ── 載入資料 ──────────────────────────────────────────────────
  // 固定顯示一定數量的K棒（參考看盤App的體驗：框框大小不變，靠左右滑動看更早/更新的K棒，
  // 不要把整個選取區間的K棒全部硬塞進同一個寬度，不然區間一長K棒就會被壓得很細）。
  // 週期按鈕仍然決定「預設從哪裡開始看」，只是超過上限的部分改用滑動去看，不會被壓縮。
  const MAX_VISIBLE_BARS = 50;

  function applyVisibleRange(p) {
    if (!chartRef.current || !data?.length) return;
    const isUnix   = typeof data[0]?.date === "number";
    const fromDate = getFromDate(p, isUnix);
    let count = 0;
    for (let i = data.length - 1; i >= 0 && data[i].date >= fromDate; i--) count++;
    const barsToShow = Math.min(Math.max(count, 5), MAX_VISIBLE_BARS, data.length);
    const to   = data.length - 1;
    const from = Math.max(0, to - barsToShow + 1);
    chartRef.current.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: to + 0.5 });
  }

  useEffect(() => {
    if (!candleSeriesRef.current || !data?.length) return;

    dataRef.current = data;
    const indexMap  = new Map();
    data.forEach((d, i) => indexMap.set(String(d.date), i));
    dataIndexRef.current = indexMap;

    const isUnix = typeof data[0]?.date === "number";
    chartRef.current?.applyOptions({
      timeScale: { borderColor: "#1e3a5f", timeVisible: isUnix },
    });

    // K線
    candleSeriesRef.current.setData(
      data.map((d) => ({ time: d.date, open: d.open, high: d.high, low: d.low, close: d.close }))
    );

    // MA + maMap
    const maMap = new Map();
    MA_CONFIG.forEach(({ key, period: mp, ema }) => {
      const arr = ema ? calcEMA(data, mp) : calcMA(data, mp);
      maSeriesRefs.current[key]?.setData(arr);
      arr.forEach((item) => {
        const k = String(item.time);
        if (!maMap.has(k)) maMap.set(k, {});
        maMap.get(k)[key] = item.value;
      });
    });
    maMapRef.current = maMap;

    // BOLL + bollMap
    const { upper, mid, lower } = calcBOLL(data);
    bollUpperRef.current?.setData(upper);
    bollMidRef.current?.setData(mid);
    bollLowerRef.current?.setData(lower);
    const bollMap = new Map();
    upper.forEach((item, i) => {
      bollMap.set(String(item.time), { up: item.value, mid: mid[i]?.value, dn: lower[i]?.value });
    });
    bollMapRef.current = bollMap;

    // 量能 + volMap
    const volData = data.map((d) => ({
      time:  d.date,
      value: d.volume != null ? Math.round(d.volume / 1000) : 0,
      color: (d.close >= d.open) ? "rgba(220,38,38,0.55)" : "rgba(22,163,74,0.55)",
    }));
    volSeriesRef.current?.setData(volData);

    const vm5  = calcVolMA(data, 5);
    const vm10 = calcVolMA(data, 10);
    const vm20 = calcVolMA(data, 20);
    volMa5Ref.current?.setData(vm5);
    volMa10Ref.current?.setData(vm10);
    volMa20Ref.current?.setData(vm20);

    const volMap = new Map();
    data.forEach((d) => volMap.set(String(d.date), { vol: d.volume != null ? Math.round(d.volume / 1000) : 0 }));
    vm5.forEach((item)  => { const v = volMap.get(String(item.time)); if (v) v.ma5  = item.value; });
    vm10.forEach((item) => { const v = volMap.get(String(item.time)); if (v) v.ma10 = item.value; });
    vm20.forEach((item) => { const v = volMap.get(String(item.time)); if (v) v.ma20 = item.value; });
    volMapRef.current = volMap;

    // MACD + macdMap（可選）
    if (showMACD) {
      const { difArr, deaArr, histArr } = calcMACD(data);
      difSeriesRef.current?.setData(difArr);
      deaSeriesRef.current?.setData(deaArr);
      macdHistRef.current?.setData(histArr);
      const macdMap = new Map();
      histArr.forEach((item) => {
        const dif = difArr.find((d) => String(d.time) === String(item.time));
        const dea = deaArr.find((d) => String(d.time) === String(item.time));
        macdMap.set(String(item.time), { dif: dif?.value, dea: dea?.value, hist: item.value });
      });
      macdMapRef.current = macdMap;
    } else {
      macdMapRef.current = new Map();
    }

    // KD (Stochastic 9) + kdMap
    const { kArr, dArr } = calcKD(data);
    kSeriesRef.current?.setData(kArr);
    dSeriesRef.current?.setData(dArr);
    const kdMap = new Map();
    kArr.forEach((item, i) => {
      kdMap.set(String(item.time), { k: item.value, d: dArr[i]?.value });
    });
    kdMapRef.current = kdMap;

    // lastBar（無 hover 時顯示最後一根）
    const last    = data[data.length - 1];
    const prev    = data.length > 1 ? data[data.length - 2] : null;
    const lastKey = String(last.date);
    const change  = prev ? +(last.close - prev.close).toFixed(2) : 0;
    const chgPct  = prev ? +((change / prev.close) * 100).toFixed(2) : 0;
    setLastBar({
      time: last.date, open: last.open, high: last.high, low: last.low, close: last.close,
      change, chgPct,
      ma:    maMap.get(lastKey),
      boll:  bollMap.get(lastKey),
      volMa: volMap.get(lastKey),
    });
    setLastMACD(macdMapRef.current.get(lastKey) ?? null);
    setLastKD(kdMap.get(lastKey) ?? null);

    applyVisibleRange(period);
  }, [data]);

  useEffect(() => { applyVisibleRange(period); }, [period]);

  useEffect(() => {
    MA_CONFIG.forEach(({ key }) => {
      maSeriesRefs.current[key]?.applyOptions({ visible: activeMA[key] });
    });
  }, [activeMA]);

  useEffect(() => {
    [bollUpperRef, bollMidRef, bollLowerRef].forEach((r) =>
      r.current?.applyOptions({ visible: showBOLL })
    );
  }, [showBOLL]);

  const toggleMA = (key) => setActiveMA((p) => ({ ...p, [key]: !p[key] }));

  const isUnix  = data?.length > 0 && typeof data[0].date === "number";
  const bar     = hoveredBar  ?? lastBar;
  const mac     = hoveredMACD ?? lastMACD;
  const kd      = hoveredKD   ?? lastKD;
  const clrC    = bar?.change > 0 ? "#dc2626" : bar?.change < 0 ? "#16a34a" : "#64748b";
  const sign    = (v) => v > 0 ? "+" : "";

  const kPaneHeight      = height;
  const totalChartHeight = height + VOL_PANE_HEIGHT + (showMACD ? MACD_PANE_HEIGHT : 0) + KD_PANE_HEIGHT;

  return (
    <div style={{ position: "relative" }}>

      {/* MA 切換列 */}
      <div className="ma-toggle-bar">
        {MA_CONFIG.map(({ key, label, color }) => (
          <button key={key}
            className={`ma-toggle-btn ${activeMA[key] ? "active" : ""}`}
            style={{ "--ma-color": color }}
            onClick={() => toggleMA(key)}
          >
            <span className="ma-dot" />{label}
          </button>
        ))}
        <button
          className={`ma-toggle-btn ${showBOLL ? "active" : ""}`}
          style={{ "--ma-color": "#7c3aed" }}
          onClick={() => setShowBOLL((v) => !v)}
        >
          <span className="ma-dot" />BOLL
        </button>
      </div>

      {/* 資訊列區（共 2～3 行） */}
      <div className="chart-info-bars">
        {/* 行 1: OHLC + 漲跌 + 量 */}
        <div className="chart-info-line">
          {bar ? (
            <>
              <span className="ci-label">時間:</span>
              <span>{fmtTime(bar.time, isUnix)}</span>
              <span className="ci-label">開:</span><span>{bar.open}</span>
              <span className="ci-label">高:</span><span>{bar.high}</span>
              <span className="ci-label">低:</span><span>{bar.low}</span>
              <span className="ci-label">收:</span>
              <span style={{ color: clrC }}>{bar.close}</span>
              <span style={{ color: clrC }}>{sign(bar.change)}{bar.change} ({sign(bar.chgPct)}{bar.chgPct}%)</span>
              {bar.volMa?.vol != null && (
                <><span className="ci-label">成交量:</span><span>{fmtVol(bar.volMa.vol)}</span></>
              )}
            </>
          ) : <span className="ci-label">—</span>}
        </div>

        {/* 行 2: MA 值 */}
        <div className="chart-info-line">
          <span className="ci-label">MA(5,10,30,60)</span>
          {bar?.ma && MA_CONFIG.map(({ key, label, color }) =>
            bar.ma[key] != null ? (
              <span key={key} style={{ color }}>{label}: {bar.ma[key]}</span>
            ) : null
          )}
        </div>

        {/* 行 3: BOLL（僅 showBOLL 時顯示） */}
        {showBOLL && (
          <div className="chart-info-line">
            <span className="ci-label">BOLL(20,2)</span>
            {bar?.boll ? (
              <>
                <span style={{ color: "#7c3aed" }}>UP: {bar.boll.up}</span>
                <span style={{ color: "#a78bfa" }}>MID: {bar.boll.mid}</span>
                <span style={{ color: "#7c3aed" }}>DN: {bar.boll.dn}</span>
              </>
            ) : <span className="ci-label">—</span>}
          </div>
        )}
      </div>

      {/* 圖表本體：固定高度確保 lightweight-charts 可以正確測量 */}
      <div ref={containerRef} style={{ height: totalChartHeight, position: "relative" }}>
        {/* VOL 副圖標籤 */}
        <div className="kd-label-bar" style={{ top: volTop }}>
          <span className="kd-label-title">VOL(5,10,20)</span>
          {bar?.volMa && (
            <>
              <span style={{ color: "#f59e0b" }}>MA5: {fmtVol(bar.volMa.ma5)}</span>
              <span style={{ color: "#38bdf8" }}>MA10: {fmtVol(bar.volMa.ma10)}</span>
              <span style={{ color: "#f97316" }}>MA20: {fmtVol(bar.volMa.ma20)}</span>
              <span style={{ color: "#94a3b8" }}>VOLUME: {fmtVol(bar.volMa.vol)}</span>
            </>
          )}
        </div>

        {/* MACD 副圖標籤（可選） */}
        {showMACD && (
          <div className="kd-label-bar" style={{ top: macdTop }}>
            <span className="kd-label-title">MACD(12,26,9)</span>
            {mac ? (
              <>
                <span style={{ color: "#fbbf24" }}>DIF: {mac.dif?.toFixed(4)}</span>
                <span style={{ color: "#60a5fa" }}>DEA: {mac.dea?.toFixed(4)}</span>
                <span style={{ color: mac.hist >= 0 ? "#dc2626" : "#16a34a" }}>
                  MACD: {mac.hist?.toFixed(4)}
                </span>
              </>
            ) : null}
          </div>
        )}

        {/* KD 副圖標籤 */}
        <div className="kd-label-bar" style={{ top: kdTop }}>
          <span className="kd-label-title">KD(9)</span>
          {kd ? (
            <>
              <span className="kd-k-val">K: {kd.k?.toFixed(2)}</span>
              <span className="kd-d-val">D: {kd.d?.toFixed(2)}</span>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
