import { useState, useEffect } from "react";
import { getMarketOverview } from "../api";
import { hasTodayCloseData } from "../marketHours";

const SCAN_LABELS = {
  near_ema60:            "📈 EMA60近線",
  volume_breakout:       "💥 量價突破",
  ma_squeeze:            "⚡ 鳥嘴與分歧",
  institutional_buying:  "🏦 法人連買",
};

function fmtSigned(v, suffix = "") {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toLocaleString()}${suffix}`;
}

function TaiexCard({ taiex }) {
  if (!taiex || taiex.price == null) {
    return (
      <div className="futures-quote">
        <div className="futures-quote-loading">大盤指數暫無資料</div>
      </div>
    );
  }
  const up = taiex.change > 0;
  const down = taiex.change < 0;
  return (
    <div className="futures-quote">
      <div className="futures-quote-main">
        <span className="futures-symbol">加權指數</span>
        <span className={`futures-price ${up ? "up" : down ? "down" : ""}`}>
          {taiex.price.toLocaleString()}
        </span>
        {taiex.change != null && (
          <span className={`futures-change ${up ? "up" : down ? "down" : ""}`}>
            {up ? "▲" : down ? "▼" : ""} {Math.abs(taiex.change)} ({fmtSigned(taiex.change_pct, "%")})
          </span>
        )}
      </div>
      <div className="futures-quote-detail">
        <span>昨收 <b>{taiex.prev_close?.toLocaleString() ?? "—"}</b></span>
      </div>
    </div>
  );
}

function BreadthAndInstitutional({ breadth, institutional }) {
  const b = breadth || {};
  const i = institutional || {};
  return (
    <div className="info-grid">
      <div className="info-item">
        <span className="info-label">漲跌家數</span>
        <span className="info-value">
          <span className="up">{b.up ?? "—"}</span>
          {" / "}
          <span className="down">{b.down ?? "—"}</span>
        </span>
        <span className="info-label">平盤 {b.flat ?? "—"}</span>
      </div>
      <div className="info-item">
        <span className="info-label">外資買賣超(張)</span>
        <span className={`info-value ${i.foreign_net_zhang > 0 ? "up" : i.foreign_net_zhang < 0 ? "down" : ""}`}>
          {fmtSigned(i.foreign_net_zhang)}
        </span>
      </div>
      <div className="info-item">
        <span className="info-label">投信買賣超(張)</span>
        <span className={`info-value ${i.trust_net_zhang > 0 ? "up" : i.trust_net_zhang < 0 ? "down" : ""}`}>
          {fmtSigned(i.trust_net_zhang)}
        </span>
      </div>
      <div className="info-item">
        <span className="info-label">自營商買賣超(張)</span>
        <span className={`info-value ${i.dealer_net_zhang > 0 ? "up" : i.dealer_net_zhang < 0 ? "down" : ""}`}>
          {fmtSigned(i.dealer_net_zhang)}
        </span>
      </div>
    </div>
  );
}

function ScanCountsCard({ scanCounts, onNavigate }) {
  return (
    <div className="stock-card market-panel">
      <h3 className="paper-section-title">📋 {hasTodayCloseData() ? "今日訊號" : "昨日訊號"}</h3>
      <div className="market-link-list">
        {Object.entries(SCAN_LABELS).map(([key, label]) => (
          <div key={key} className="market-link-row" onClick={() => onNavigate("screener")}>
            <span>{label}</span>
            <span className="market-link-count">{scanCounts?.[key] ?? "—"} 支 →</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function FuturesCard({ futures, onNavigate }) {
  const q = futures?.quote;
  const pos = futures?.positions_latest;
  const up = q?.change > 0;
  const down = q?.change < 0;
  return (
    <div className="stock-card market-panel" onClick={() => onNavigate("futures")} style={{ cursor: "pointer" }}>
      <h3 className="paper-section-title">📈 台指期／法人期貨部位</h3>
      {q?.price != null ? (
        <div className="market-link-row">
          <span>{q.symbol}</span>
          <span className={up ? "up" : down ? "down" : ""}>
            {q.price.toLocaleString()} {up ? "▲" : down ? "▼" : ""} {fmtSigned(q.change_pct, "%")}
          </span>
        </div>
      ) : (
        <p className="no-data">台指期報價暫無資料</p>
      )}
      {pos ? (
        <>
          <div className="market-link-row"><span>外資淨部位(口)</span><span className={pos.foreign > 0 ? "up" : pos.foreign < 0 ? "down" : ""}>{fmtSigned(pos.foreign)}</span></div>
          <div className="market-link-row"><span>投信淨部位(口)</span><span className={pos.trust > 0 ? "up" : pos.trust < 0 ? "down" : ""}>{fmtSigned(pos.trust)}</span></div>
          <div className="market-link-row"><span>自營商淨部位(口)</span><span className={pos.dealer > 0 ? "up" : pos.dealer < 0 ? "down" : ""}>{fmtSigned(pos.dealer)}</span></div>
        </>
      ) : (
        <p className="no-data">法人期貨部位暫無資料</p>
      )}
    </div>
  );
}

function IndustryList({ title, industries, onSelectIndustry }) {
  return (
    <div className="stock-card market-panel">
      <h3 className="paper-section-title">{title}</h3>
      {!industries?.length ? (
        <p className="no-data">暫無資料</p>
      ) : (
        industries.map((ind) => (
          <div
            key={ind.industry}
            className="market-link-row market-link-clickable"
            onClick={() => onSelectIndustry(ind.industry)}
          >
            <span>{ind.industry}</span>
            <span className={ind.avg_change_pct > 0 ? "up" : ind.avg_change_pct < 0 ? "down" : ""}>
              {fmtSigned(ind.avg_change_pct, "%")}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

function MoversList({ title, stocks, onSelect }) {
  return (
    <div className="stock-card market-panel">
      <h3 className="paper-section-title">{title}</h3>
      {!stocks?.length ? (
        <p className="no-data">暫無資料</p>
      ) : (
        stocks.map((s) => (
          <div
            key={s.ticker}
            className="market-link-row market-link-clickable"
            onClick={() => onSelect(s.ticker)}
          >
            <span>{s.ticker} {s.name}</span>
            <span className={s.change_pct > 0 ? "up" : s.change_pct < 0 ? "down" : ""}>
              {fmtSigned(s.change_pct, "%")}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

export default function MarketOverview({ onSelect, onSelectIndustry, onNavigate }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  const load = () => {
    setLoading(true);
    setError(null);
    getMarketOverview()
      .then((res) => setData(res.data))
      .catch((e) => setError(e?.response?.data?.detail || e.message || "載入失敗"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="page market-overview-page">
      <div className="ranking-header">
        <h2>大盤狀態</h2>
        <button className="refresh-btn" onClick={load} disabled={loading}>
          {loading ? "更新中..." : "↻ 重新整理"}
        </button>
      </div>

      {error && <p className="error">❌ {error}</p>}
      {loading && !data && <p className="loading-hint">載入中...</p>}

      {data && (
        <>
          <TaiexCard taiex={data.taiex} />
          <BreadthAndInstitutional breadth={data.breadth} institutional={data.institutional} />

          <div className="market-overview-cols">
            <ScanCountsCard scanCounts={data.scan_counts} onNavigate={onNavigate} />
            <FuturesCard futures={data.futures} onNavigate={onNavigate} />
          </div>

          <div className="market-overview-cols">
            <IndustryList title="🔥 今日強勢產業 Top5" industries={data.industry_top5} onSelectIndustry={onSelectIndustry} />
            <IndustryList title="❄️ 今日弱勢產業 Top5" industries={data.industry_bottom5} onSelectIndustry={onSelectIndustry} />
          </div>

          <div className="market-overview-cols">
            <MoversList title="📈 漲幅王 Top5" stocks={data.movers_up_top5} onSelect={onSelect} />
            <MoversList title="📉 跌幅王 Top5" stocks={data.movers_down_top5} onSelect={onSelect} />
          </div>
        </>
      )}
    </div>
  );
}
