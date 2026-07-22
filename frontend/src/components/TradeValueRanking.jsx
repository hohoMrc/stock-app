import { useState, useEffect, useRef } from "react";
import { getTradeValueRanking, getTurnoverRanking, getMoversRanking, getIndustryPerformance } from "../api";
import { isTradingHours } from "../marketHours";

const TABS = [
  { key: "value",    label: "成交值" },
  { key: "turnover", label: "週轉率" },
  { key: "up",       label: "漲幅" },
  { key: "down",     label: "跌幅" },
  { key: "industry", label: "產業" },
];

const INIT_STATE = { value: [], turnover: [], up: [], down: [], industry: [] };

export default function TradeValueRanking({ onSelect, onSelectIndustry }) {
  const [activeTab, setActiveTab]   = useState("value");
  const [data, setData]             = useState(INIT_STATE);
  const [loading, setLoading]       = useState({ value: false, turnover: false, up: false, down: false, industry: false });
  const [error, setError]           = useState({ value: null, turnover: null, up: null, down: null, industry: null });
  const [updatedAt, setUpdatedAt]   = useState({ value: null, turnover: null, up: null, down: null, industry: null });
  const loaded = useRef({ value: false, turnover: false, up: false, down: false, industry: false });

  const load = async (tab, force = false) => {
    setLoading((p) => ({ ...p, [tab]: true }));
    setError((p) => ({ ...p, [tab]: null }));
    try {
      const res = tab === "value"    ? await getTradeValueRanking(50, force)
                : tab === "turnover" ? await getTurnoverRanking(50, force)
                : tab === "industry" ? await getIndustryPerformance(force)
                : await getMoversRanking(tab, 50, force); // tab === "up" | "down"
      setData((p) => ({ ...p, [tab]: tab === "industry" ? res.data.industries : res.data.stocks }));
      setUpdatedAt((p) => ({
        ...p,
        [tab]: new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" }),
      }));
      loaded.current[tab] = true;
    } catch (e) {
      setError((p) => ({ ...p, [tab]: e?.response?.data?.detail || e.message || "載入失敗" }));
    } finally {
      setLoading((p) => ({ ...p, [tab]: false }));
    }
  };

  const pollRef = useRef(null);

  useEffect(() => { load("value"); }, []);

  useEffect(() => {
    if (!loaded.current[activeTab]) load(activeTab);
  }, [activeTab]);

  // 交易時段每 60 秒自動刷新成交值排行
  useEffect(() => {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(() => {
      if (isTradingHours()) load(activeTab, true);
    }, 60_000);
    return () => clearInterval(pollRef.current);
  }, [activeTab]);

  const stocks   = data[activeTab];
  const isLoading = loading[activeTab];
  const err      = error[activeTab];
  const time     = updatedAt[activeTab];

  const HINTS = {
    value:    "盤中即時排行（Fugle）；非交易時段自動退回 TWSE／TPEx 收盤資料。快取 5 分鐘。",
    turnover: "週轉率 = 成交量 ÷ 在外流通股數（以實收資本額 ÷ 面額 10 元估算）。快取 5 分鐘。",
    up:       "盤中即時漲幅排行（Fugle snapshot/movers），合併上市＋上櫃。快取 5 分鐘。",
    down:     "盤中即時跌幅排行（Fugle snapshot/movers），合併上市＋上櫃。快取 5 分鐘。",
    industry: "依 TWSE 產業大分類計算各產業平均漲跌幅（盤中即時），找出當天熱門產業。快取 5 分鐘。",
  };

  return (
    <div className="page">
      <div className="ranking-header">
        <h2>排行榜</h2>
        <div className="ranking-meta">
          {time && <span className="ranking-time">更新：{time}</span>}
          <button className="refresh-btn" onClick={() => load(activeTab, true)} disabled={isLoading}>
            {isLoading ? "載入中..." : "↻ 重新整理"}
          </button>
        </div>
      </div>

      <div className="ranking-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`ranking-tab ${activeTab === t.key ? "active" : ""}`}
            onClick={() => setActiveTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <p className="ranking-hint">{HINTS[activeTab]}</p>

      {err && <p className="error">❌ {err}</p>}
      {!isLoading && !err && stocks.length === 0 && (
        <p className="no-data">暫無資料（可能尚未收盤）</p>
      )}

      {stocks.length > 0 && (
        <div className="ranking-table-wrap">
          {activeTab === "industry" ? (
            <IndustryTable industries={stocks} onSelect={onSelectIndustry} />
          ) : activeTab === "turnover" ? (
            <TurnoverTable stocks={stocks} onSelect={onSelect} />
          ) : (
            <ValueTable stocks={stocks} onSelect={onSelect} />
          )}
        </div>
      )}
    </div>
  );
}

function RowWrapper({ s, children }) {
  const up   = s.change > 0;
  const down = s.change < 0;
  return <tr className={up ? "row-up" : down ? "row-down" : ""}>{children}</tr>;
}

function isLimitUp(s) {
  if (s.is_limit_up != null) return s.is_limit_up;
  return s.change_pct != null && s.change_pct >= 9.5;
}

function isLimitDown(s) {
  if (s.is_limit_down != null) return s.is_limit_down;
  return s.change_pct != null && s.change_pct <= -9.5;
}

function CloseCell({ s }) {
  const up   = isLimitUp(s);
  const down = isLimitDown(s);
  const style = up
    ? { background: "rgba(239,68,68,0.30)", borderRadius: 4, padding: "2px 6px" }
    : down
    ? { background: "rgba(34,197,94,0.25)", borderRadius: 4, padding: "2px 6px" }
    : {};
  return <td><span style={style}>{s.close ?? "—"}</span></td>;
}

function ChangeCells({ s }) {
  const sign = s.change > 0 ? "+" : "";
  return (
    <>
      <td>{s.change != null ? `${sign}${s.change}` : "—"}</td>
      <td>{s.change_pct != null ? `${sign}${s.change_pct}%` : "—"}</td>
    </>
  );
}

function ExchangeBadge({ exchange }) {
  return (
    <td className="exchange-badge-cell">
      <span className={`exchange-badge ${exchange === "上市" ? "listed" : "otc"}`}>
        {exchange}
      </span>
    </td>
  );
}

// 手機版排行榜卡片列表，取代原本很擠的橫向表格（桌面版仍用 <table>，這個只在手機寬度顯示）
function MobileRankList({ stocks, onSelect }) {
  return (
    <div className="mobile-rank-list">
      <div className="mobile-rank-header">
        <span>成交</span><span>漲跌</span><span>漲跌幅</span>
      </div>
      {stocks.map((s) => {
        const dir  = s.change > 0 ? "up" : s.change < 0 ? "down" : "";
        const sign = s.change > 0 ? "+" : "";
        const up   = isLimitUp(s);
        const down = isLimitDown(s);
        return (
          <div key={s.ticker} className="mobile-rank-card" onClick={() => onSelect(s.ticker)}>
            <div className="mrc-left">
              <div className="mrc-name">{s.name}</div>
              <div className="mrc-sub">
                <span className="mrc-exchange-tag">{s.exchange === "上市" ? "市" : "櫃"}</span>
                <span className="mrc-ticker">{s.ticker}</span>
              </div>
            </div>
            <div className="mrc-right">
              <span className={`mrc-close ${up ? "limit-up" : down ? "limit-down" : ""}`}>{s.close ?? "—"}</span>
              <span className={`mrc-num ${dir}`}>{s.change != null ? `${sign}${s.change}` : "—"}</span>
              <span className={`mrc-num ${dir}`}>{s.change_pct != null ? `${sign}${s.change_pct}%` : "—"}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ValueTable({ stocks, onSelect }) {
  return (
    <>
      <table className="result-table">
        <thead>
          <tr>
            <th>#</th><th>代號</th><th>名稱</th>
            <th>收盤</th><th>漲跌</th><th>漲跌幅</th>
            <th>成交值(億)</th><th>市場</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {stocks.map((s, i) => (
            <RowWrapper key={s.ticker} s={s}>
              <td className="rank-num">{i + 1}</td>
              <td className="col-ticker">{s.ticker}</td>
              <td className="col-name">{s.name}</td>
              <CloseCell s={s} />
              <ChangeCells s={s} />
              <td className="trade-value-cell">{s.trade_value_yi ?? "—"}</td>
              <ExchangeBadge exchange={s.exchange} />
              <td><button className="view-btn" onClick={() => onSelect(s.ticker)}>查看</button></td>
            </RowWrapper>
          ))}
        </tbody>
      </table>
      <MobileRankList stocks={stocks} onSelect={onSelect} />
    </>
  );
}

function IndustryTable({ industries, onSelect }) {
  return (
    <table className="result-table">
      <thead>
        <tr>
          <th>#</th><th>產業</th><th>平均漲跌幅</th><th>成交值(億)</th><th>檔數</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        {industries.map((ind, i) => {
          const up   = ind.avg_change_pct > 0;
          const down = ind.avg_change_pct < 0;
          const sign = up ? "+" : "";
          return (
            <tr key={ind.industry} className={up ? "row-up" : down ? "row-down" : ""}>
              <td className="rank-num">{i + 1}</td>
              <td className="col-name">{ind.industry}</td>
              <td>{sign}{ind.avg_change_pct}%</td>
              <td className="trade-value-cell">{ind.trade_value_yi}</td>
              <td>{ind.stock_count}</td>
              <td><button className="view-btn" onClick={() => onSelect(ind.industry)}>查看</button></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function TurnoverTable({ stocks, onSelect }) {
  return (
    <>
      <table className="result-table">
        <thead>
          <tr>
            <th>#</th><th>代號</th><th>名稱</th>
            <th>收盤</th><th>漲跌</th><th>漲跌幅</th>
            <th>週轉率</th><th>成交量(張)</th><th>市場</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {stocks.map((s, i) => (
            <RowWrapper key={s.ticker} s={s}>
              <td className="rank-num">{i + 1}</td>
              <td className="col-ticker">{s.ticker}</td>
              <td className="col-name">{s.name}</td>
              <CloseCell s={s} />
              <ChangeCells s={s} />
              <td className="trade-value-cell">{s.turnover_pct != null ? `${s.turnover_pct}%` : "—"}</td>
              <td>{s.trade_volume_zhang != null ? s.trade_volume_zhang.toLocaleString() : "—"}</td>
              <ExchangeBadge exchange={s.exchange} />
              <td><button className="view-btn" onClick={() => onSelect(s.ticker)}>查看</button></td>
            </RowWrapper>
          ))}
        </tbody>
      </table>
      <MobileRankList stocks={stocks} onSelect={onSelect} />
    </>
  );
}
