import { useState, useEffect } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import CandlestickChart from "./CandlestickChart";
import { getStock, getHistory, analyzeStock } from "../api";

const INTERVAL_CONFIG = {
  "1d":  { fetchPeriod: "1y", defaultPeriod: "3mo", periods: ["1mo","3mo","6mo","1y"] },
  "1wk": { fetchPeriod: "2y", defaultPeriod: "1y",  periods: ["3mo","6mo","1y","2y"] },
  "1mo": { fetchPeriod: "5y", defaultPeriod: "2y",  periods: ["1y","2y","5y"] },
};

export default function StockDetail({ ticker, onBack, onIndustry, watchlist = [], onToggleWatch }) {
  const [info, setInfo] = useState(null);
  const [history, setHistory] = useState([]);
  const [analysis, setAnalysis] = useState("");
  const [period, setPeriod] = useState("3mo");
  const [chartType, setChartType] = useState("candle"); // "candle" | "line"
  const [interval, setInterval] = useState("1d");       // "1d" | "1wk" | "1mo"
  const [analyzing, setAnalyzing] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const cfg = INTERVAL_CONFIG[interval];
    setPeriod(cfg.defaultPeriod);
    const load = async () => {
      setLoading(true);
      try {
        const [infoRes, histRes] = await Promise.all([
          getStock(ticker),
          getHistory(ticker, cfg.fetchPeriod, interval),
        ]);
        setInfo(infoRes.data);
        setHistory(histRes.data.data);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [ticker, interval]);

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

  return (
    <div className="page">
      <button className="back-btn" onClick={onBack}>← 返回</button>

      <div className="stock-header">
        <div>
          <div className="stock-name-row">
            <h2>{info.name}</h2>
            {onToggleWatch && (
              <button
                className={`watch-btn ${watchlist.includes(ticker) ? "watched" : ""}`}
                onClick={() => onToggleWatch(ticker)}
                title={watchlist.includes(ticker) ? "從自選清單移除" : "加入自選清單"}
              >
                {watchlist.includes(ticker) ? "★ 已加入" : "☆ 加入自選"}
              </button>
            )}
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
        <div className="price-block">
          <span className="price">{info.price} 元</span>
        </div>
      </div>

      <div className="info-grid">
        <InfoItem label="殖利率" value={info.dividend_yield ? `${info.dividend_yield}%` : "—"} />
        <InfoItem label="52週高" value={info.week_52_high ?? "—"} />
        <InfoItem label="52週低" value={info.week_52_low ?? "—"} />
      </div>

      <div className="chart-section">
        <div className="chart-header">
          <div className="chart-header-left">
            <h3>股價走勢</h3>
            <div className="chart-type-btns">
              {[
                { label: "日K",  type: "candle", iv: "1d" },
                { label: "週K",  type: "candle", iv: "1wk" },
                { label: "月K",  type: "candle", iv: "1mo" },
                { label: "折線", type: "line",   iv: "1d" },
              ].map(({ label, type, iv }) => (
                <button
                  key={label}
                  className={(chartType === type && (type === "line" || interval === iv)) ? "active" : ""}
                  onClick={() => { setChartType(type); if (type === "candle") setInterval(iv); }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="period-btns">
            {INTERVAL_CONFIG[interval].periods.map((p) => (
              <button
                key={p}
                className={period === p ? "active" : ""}
                onClick={() => setPeriod(p)}
              >
                {{ "1mo":"1個月","3mo":"3個月","6mo":"6個月","1y":"1年","2y":"2年","5y":"5年" }[p]}
              </button>
            ))}
          </div>
        </div>

        {history.length > 0 ? (
          chartType === "candle" ? (
            <CandlestickChart data={history} period={period} height={320} />
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

      <div className="analysis-section">
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
