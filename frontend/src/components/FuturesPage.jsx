import { useState, useEffect, useRef } from "react";
import { createChart, CandlestickSeries, HistogramSeries } from "lightweight-charts";
import { getFuturesQuote, getFuturesCandles, getFuturesInstitutional } from "../api";

const TIMEFRAMES = [
  { key: "D",  label: "日K" },
  { key: "60", label: "60分" },
  { key: "30", label: "30分" },
  { key: "15", label: "15分" },
  { key: "5",  label: "5分" },
  { key: "1",  label: "1分" },
];

const IDENTITY_LABEL = { foreign: "外資", trust: "投信", dealer: "自營商" };
const IDENTITY_COLOR = { foreign: "#38bdf8", trust: "#f59e0b", dealer: "#a78bfa" };

function QuoteHeader({ quote, loading }) {
  if (loading) return <div className="futures-quote-loading">載入中...</div>;
  if (!quote)  return null;
  const up = quote.change >= 0;
  return (
    <div className="futures-quote">
      <div className="futures-quote-main">
        <span className="futures-symbol">{quote.symbol}</span>
        <span className="futures-name">{quote.name}</span>
        <span className={`futures-price ${up ? "up" : "down"}`}>
          {quote.price?.toLocaleString()}
        </span>
        <span className={`futures-change ${up ? "up" : "down"}`}>
          {up ? "▲" : "▼"} {Math.abs(quote.change)} ({up ? "+" : ""}{quote.change_pct}%)
        </span>
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

function FuturesChart({ candles, timeframe }) {
  const containerRef = useRef(null);
  const chartRef     = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !candles.length) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
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

    candleSeries.setData(candles.map(c => ({
      time:  c.time ?? c.date,
      open:  c.open,
      high:  c.high,
      low:   c.low,
      close: c.close,
    })));

    volSeries.setData(candles.map(c => ({
      time:  c.time ?? c.date,
      value: c.volume,
      color: c.close >= c.open ? "#ef4444aa" : "#22c55eaa",
    })));

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: containerRef.current?.clientWidth || 600 });
    });
    ro.observe(containerRef.current);

    chartRef.current = chart;
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; };
  }, [candles, timeframe]);

  return <div ref={containerRef} className="futures-chart" />;
}

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
  const [timeframe,    setTimeframe]    = useState("60");
  const [quote,        setQuote]        = useState(null);
  const [candles,      setCandles]      = useState([]);
  const [institutional, setInstitutional] = useState([]);
  const [quoteLoading,  setQuoteLoading]  = useState(true);
  const [candleLoading, setCandleLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setQuoteLoading(true);
    getFuturesQuote()
      .then(r => setQuote(r.data))
      .catch(e => setError(e?.response?.data?.detail || e.message))
      .finally(() => setQuoteLoading(false));

    getFuturesInstitutional()
      .then(r => setInstitutional(r.data.data || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    setCandleLoading(true);
    setCandles([]);
    getFuturesCandles(timeframe)
      .then(r => setCandles(r.data.data || []))
      .catch(e => setError(e?.response?.data?.detail || e.message))
      .finally(() => setCandleLoading(false));
  }, [timeframe]);

  return (
    <div className="page futures-page">
      <QuoteHeader quote={quote} loading={quoteLoading} />

      {error && <p className="error">❌ {error}</p>}

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

      {candleLoading
        ? <div className="futures-chart-loading">K 線載入中...</div>
        : <FuturesChart candles={candles} timeframe={timeframe} />
      }

      <InstitutionalChart data={institutional} />
    </div>
  );
}
