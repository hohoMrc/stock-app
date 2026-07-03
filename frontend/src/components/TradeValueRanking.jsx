import { useState, useEffect, useRef } from "react";
import { getTradeValueRanking, getTurnoverRanking } from "../api";

const TABS = [
  { key: "value",    label: "成交值" },
  { key: "turnover", label: "週轉率" },
];

export default function TradeValueRanking({ onSelect }) {
  const [activeTab, setActiveTab]   = useState("value");
  const [data, setData]             = useState({ value: [], turnover: [] });
  const [loading, setLoading]       = useState({ value: false, turnover: false });
  const [error, setError]           = useState({ value: null, turnover: null });
  const [updatedAt, setUpdatedAt]   = useState({ value: null, turnover: null });
  const loaded = useRef({ value: false, turnover: false });

  const load = async (tab) => {
    setLoading((p) => ({ ...p, [tab]: true }));
    setError((p) => ({ ...p, [tab]: null }));
    try {
      const res = tab === "value"
        ? await getTradeValueRanking(50)
        : await getTurnoverRanking(50);
      setData((p) => ({ ...p, [tab]: res.data.stocks }));
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

  useEffect(() => { load("value"); }, []);

  useEffect(() => {
    if (!loaded.current[activeTab]) load(activeTab);
  }, [activeTab]);

  const stocks   = data[activeTab];
  const isLoading = loading[activeTab];
  const err      = error[activeTab];
  const time     = updatedAt[activeTab];

  const HINTS = {
    value:    "盤中即時排行（Fugle）；非交易時段自動退回 TWSE／TPEx 收盤資料。快取 5 分鐘。",
    turnover: "週轉率 = 成交量 ÷ 在外流通股數（以實收資本額 ÷ 面額 10 元估算）。快取 5 分鐘。",
  };

  return (
    <div className="page">
      <div className="ranking-header">
        <h2>排行榜</h2>
        <div className="ranking-meta">
          {time && <span className="ranking-time">更新：{time}</span>}
          <button className="refresh-btn" onClick={() => load(activeTab)} disabled={isLoading}>
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
          {activeTab === "value" ? (
            <ValueTable stocks={stocks} onSelect={onSelect} />
          ) : (
            <TurnoverTable stocks={stocks} onSelect={onSelect} />
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

function ValueTable({ stocks, onSelect }) {
  return (
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
  );
}

function TurnoverTable({ stocks, onSelect }) {
  return (
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
  );
}
