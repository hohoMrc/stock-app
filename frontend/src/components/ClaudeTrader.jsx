import { useState, useEffect } from "react";
import { getClaudePortfolio, getClaudeStrategyConfig } from "../api";
import Pagination, { PAGE_SIZE } from "./Pagination";

export default function ClaudeTrader({ onSelect }) {
  const [strategy, setStrategy] = useState("longterm");
  const [portfolio, setPortfolio] = useState(null);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [ordersPage, setOrdersPage] = useState(1);

  useEffect(() => {
    setLoading(true);
    setOrdersPage(1);
    Promise.all([getClaudePortfolio(strategy), getClaudeStrategyConfig()])
      .then(([pRes, cRes]) => {
        setPortfolio(pRes.data);
        setConfig(cRes.data);
      })
      .catch(() => { setPortfolio(null); setConfig(null); })
      .finally(() => setLoading(false));
  }, [strategy]);

  const account   = portfolio?.account;
  const positions = portfolio?.positions ?? [];
  const orders    = portfolio?.orders ?? [];

  const ordersTotalPages = Math.max(1, Math.ceil(orders.length / PAGE_SIZE));
  const ordersCurPage    = Math.min(ordersPage, ordersTotalPages);
  const pagedOrders      = orders.slice((ordersCurPage - 1) * PAGE_SIZE, ordersCurPage * PAGE_SIZE);

  return (
    <div className="page">
      <h2>Claude 自動選股交易</h2>
      <p className="ranking-hint">
        規則全自動執行、公開透明的模擬交易，不是即時人工判斷——用來當學習/驗證選股邏輯的參考，
        不是投資建議。長期投資：本益比／殖利率／站上EMA60三個條件選股，每月審視換股一次；另外每天
        都會檢查保底停損，單筆虧損跌破門檻不用等到月度審視就會立刻出場。
        短期交易：直接用「量價突破」「法人連買」「EMA60貼線噴出」的訊號進場，固定停損或持有滿
        20個交易日出場。兩邊的訊號來源權重／門檻都會依實際績效每月/每季自動調整，不是一套規則用到底。
      </p>

      <div className="paper-side-tabs">
        <button className={strategy === "longterm" ? "active" : ""} onClick={() => setStrategy("longterm")}>長期投資</button>
        <button className={strategy === "shortterm" ? "active" : ""} onClick={() => setStrategy("shortterm")}>短期交易</button>
      </div>

      {loading ? (
        <p className="no-data">載入中...</p>
      ) : !account ? (
        <p className="no-data">帳戶尚未建立，等排程第一次執行後就會出現</p>
      ) : (
        <>
          <div className="info-grid paper-summary">
            <div className="info-item">
              <span className="info-label">現金</span>
              <span className="info-value">{account.cash.toLocaleString()}</span>
            </div>
            <div className="info-item">
              <span className="info-label">持股市值</span>
              <span className="info-value">{account.market_value.toLocaleString()}</span>
            </div>
            <div className="info-item">
              <span className="info-label">總資產</span>
              <span className="info-value">{account.equity.toLocaleString()}</span>
            </div>
            <div className="info-item">
              <span className="info-label">未實現損益</span>
              <span className={`info-value ${account.unrealized_pl > 0 ? "up" : account.unrealized_pl < 0 ? "down" : ""}`}>
                {account.unrealized_pl.toLocaleString()}
              </span>
            </div>
            <div className="info-item">
              <span className="info-label">已實現損益</span>
              <span className={`info-value ${account.realized_pl > 0 ? "up" : account.realized_pl < 0 ? "down" : ""}`}>
                {account.realized_pl.toLocaleString()}
              </span>
            </div>
          </div>

          {config && (
            <p className="ranking-hint">
              {strategy === "longterm"
                ? `目前門檻：本益比 < ${config.lt_max_pe}、殖利率 > ${config.lt_min_div_yield}%、目標持股 ${config.lt_target_holdings} 檔、保底停損 ${config.lt_stop_loss_pct}%`
                : `目前設定：單筆倉位約 ${(config.st_position_pct * 100).toFixed(0)}%、停損 ${config.st_stop_loss_pct}%、最長持有 ${config.st_max_hold_days} 個交易日、上限 ${config.st_max_positions} 檔　`
                  + `訊號權重：${Object.entries(config.st_scan_weights || {}).map(([k, v]) => `${k}=${v}`).join("、")}`}
            </p>
          )}

          <h3 className="paper-section-title">目前持股</h3>
          {positions.length === 0 ? (
            <p className="no-data">目前無持股</p>
          ) : (
            <div className="ranking-table-wrap">
              <table className="result-table">
                <thead>
                  <tr>
                    <th>代號</th><th>名稱</th><th>買入日期</th><th>張數</th><th>均價</th><th>現價</th>
                    <th>未實現損益</th><th>報酬率</th><th>買進理由</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr
                      key={p.ticker}
                      className={`industry-row-clickable ${p.unrealized_pl > 0 ? "row-up" : p.unrealized_pl < 0 ? "row-down" : ""}`}
                      onClick={() => onSelect(p.ticker)}
                    >
                      <td className="col-ticker">{p.ticker}</td>
                      <td>{p.name}</td>
                      <td>{p.buy_date ? new Date(p.buy_date * 1000).toLocaleDateString("zh-TW") : "—"}</td>
                      <td>{p.lots}</td>
                      <td>{p.avg_cost}</td>
                      <td>{p.price ?? "—"}</td>
                      <td>{p.unrealized_pl?.toLocaleString() ?? "—"}</td>
                      <td>{p.return_pct != null ? `${p.return_pct}%` : "—"}</td>
                      <td className="reason-cell">{p.reason ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3 className="paper-section-title">歷史成交紀錄</h3>
          {orders.length === 0 ? (
            <p className="no-data">尚無成交紀錄</p>
          ) : (
            <div className="ranking-table-wrap">
              <table className="result-table">
                <thead>
                  <tr>
                    <th>時間</th><th>代號</th><th>名稱</th><th>買賣</th><th>張數</th>
                    <th>成交價</th><th>已實現損益</th><th>理由</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedOrders.map((o, i) => (
                    <tr key={i} className="industry-row-clickable" onClick={() => onSelect(o.ticker)}>
                      <td>{new Date(o.created_at * 1000).toLocaleString("zh-TW", { hour12: false })}</td>
                      <td className="col-ticker">{o.ticker}</td>
                      <td>{o.name}</td>
                      <td>{o.side === "buy" ? "買進" : o.side === "sell" ? "賣出" : o.side}</td>
                      <td>{o.qty ? Math.round(o.qty / 1000) : "—"}</td>
                      <td>{o.price}</td>
                      <td>{o.realized_pl != null ? o.realized_pl.toLocaleString() : "—"}</td>
                      <td className="reason-cell">{o.reason ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pagination page={ordersCurPage} totalPages={ordersTotalPages} onChange={setOrdersPage} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
