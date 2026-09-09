import { useState, useEffect, useRef, forwardRef, useImperativeHandle } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import {
  searchStocks, getStock, getDaytradePaperAccount, getDaytradePaperPositions, getDaytradePaperOrders,
  placeDaytradePaperOrder, depositDaytradePaperCash, getDaytradePaperPerformance,
} from "../api";
import { calcFee, calcTax, DAY_TRADE_TAX_RATE } from "../feeCalc";
import PaperOrderModal from "./PaperOrderModal";
import Pagination, { PAGE_SIZE } from "./Pagination";

// 重新整理/入金按鈕跟「模擬下單」標題放同一列（在 PaperTrading.jsx 的頁首），
// 比照 FuturesPaperTrading.jsx 用 ref 把 refresh/deposit 動作往上暴露。
const DaytradePaperTrading = forwardRef(function DaytradePaperTrading(
  { username, onRequireLogin, loading, setLoading, setDepositing, onSelectStock },
  ref
) {
  const [account, setAccount]     = useState(null);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders]       = useState([]);
  const [performance, setPerformance] = useState(null);

  const [tickerInput, setTickerInput] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selected, setSelected]       = useState(null);
  const [side, setSide]               = useState("buy");
  const [lots, setLots]               = useState(1);
  const [submitting, setSubmitting]   = useState(false);
  const [formError, setFormError]     = useState("");
  const [formMsg, setFormMsg]         = useState("");
  const [orderModal, setOrderModal]   = useState(null);
  const [ordersPage, setOrdersPage]   = useState(1);

  const debounceRef = useRef(null);
  const wrapperRef  = useRef(null);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [accRes, posRes, ordRes, perfRes] = await Promise.all([
        getDaytradePaperAccount(), getDaytradePaperPositions(), getDaytradePaperOrders(50), getDaytradePaperPerformance(),
      ]);
      setAccount(accRes.data);
      setPositions(posRes.data.positions);
      setOrders(ordRes.data.orders);
      setPerformance(perfRes.data);
    } catch {
      // 未登入或載入失敗時保持空白，不額外報錯打擾使用者
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (username) loadAll();
  }, [username]);

  useEffect(() => {
    const handler = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setShowSuggestions(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleTickerChange = (e) => {
    const val = e.target.value;
    setTickerInput(val);
    setSelected(null);
    clearTimeout(debounceRef.current);
    if (val.trim().length < 1) { setSuggestions([]); setShowSuggestions(false); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await searchStocks(val.trim());
        setSuggestions(res.data.results);
        setShowSuggestions(res.data.results.length > 0);
      } catch {
        setSuggestions([]);
      }
    }, 100);
  };

  const pickTicker = async (ticker) => {
    setTickerInput(ticker);
    setSuggestions([]);
    setShowSuggestions(false);
    setFormError("");
    try {
      const res = await getStock(ticker);
      setSelected({ ticker: res.data.ticker, name: res.data.name, price: res.data.price });
    } catch {
      setFormError("查詢股價失敗，請確認代號");
    }
  };

  const handleSubmit = async () => {
    if (!username) { onRequireLogin(); return; }
    if (!selected) { setFormError("請先選擇股票"); return; }
    if (!lots || lots <= 0) { setFormError("張數需大於 0"); return; }
    setSubmitting(true);
    setFormError("");
    setFormMsg("");
    try {
      const res = await placeDaytradePaperOrder(selected.ticker, side, Number(lots));
      const d = res.data;
      setFormMsg(
        `${d.side === "buy" ? "買進" : "賣出"} ${d.ticker} ${d.qty / 1000} 張成交，成交價 ${d.price} 元`
      );
      setSelected(null);
      setTickerInput("");
      setLots(1);
      loadAll();
    } catch (e) {
      setFormError(e.response?.data?.detail || "下單失敗");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeposit = async () => {
    setDepositing(true);
    try {
      const res = await depositDaytradePaperCash();
      setFormMsg(`已入金 ${res.data.deposit_amount.toLocaleString()} 元`);
      setFormError("");
      loadAll();
    } catch (e) {
      setFormError(e.response?.data?.detail || "入金失敗");
    } finally {
      setDepositing(false);
    }
  };

  useImperativeHandle(ref, () => ({ refresh: loadAll, deposit: handleDeposit }));

  if (!username) {
    return (
      <div>
        <p className="no-data">請先登入才能使用當沖練習功能</p>
        <button className="login-btn" onClick={onRequireLogin}>登入 / 註冊</button>
      </div>
    );
  }

  const ordersTotalPages = Math.max(1, Math.ceil(orders.length / PAGE_SIZE));
  const ordersCurPage    = Math.min(ordersPage, ordersTotalPages);
  const pagedOrders      = orders.slice((ordersCurPage - 1) * PAGE_SIZE, ordersCurPage * PAGE_SIZE);

  const gross = selected ? selected.price * lots * 1000 : 0;
  const fee   = gross ? calcFee(gross) : 0;
  const tax   = side === "sell" && gross ? calcTax(gross, DAY_TRADE_TAX_RATE) : 0;
  const estNet = side === "buy" ? gross + fee : gross - fee - tax;

  return (
    <div>
      <p className="ranking-hint">
        當沖練習帳戶跟股票模擬下單分開計算，刻意不檢查本金是否足夠——真實現股當沖本來就
        不需要準備全額本金，只要求收盤前把部位沖銷掉，這裡把出場紀律留給你自己練習。
        賣出證交稅固定用當沖減半稅率 0.15%。不支援先賣後補，也不會自動幫你平倉。
      </p>

      {account && (
        <div className="info-grid paper-summary">
          <div className="info-item">
            <span className="info-label">現金</span>
            <span className={`info-value ${account.cash < 0 ? "down" : ""}`}>{account.cash.toLocaleString()}</span>
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
      )}

      <h3 className="paper-section-title">持股</h3>
      {positions.length === 0 ? (
        <p className="no-data">{loading ? "載入中..." : "目前無持股"}</p>
      ) : (
        <div className="ranking-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                <th>代號</th><th>名稱</th><th>張數</th><th>均價</th><th>現價</th>
                <th>市值</th><th>未實現損益</th><th>報酬率</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr
                  key={p.ticker}
                  className={`paper-position-row ${p.unrealized_pl > 0 ? "row-up" : p.unrealized_pl < 0 ? "row-down" : ""}`}
                  onClick={() => onSelectStock && onSelectStock(p.ticker)}
                  title="查看股價走勢"
                >
                  <td className="col-ticker">{p.ticker}</td>
                  <td className="col-name">{p.name ?? "—"}</td>
                  <td>{p.lots}</td>
                  <td>{p.avg_cost}</td>
                  <td>{p.price ?? "—"}</td>
                  <td>{p.market_value?.toLocaleString() ?? "—"}</td>
                  <td>{p.unrealized_pl?.toLocaleString() ?? "—"}</td>
                  <td>{p.return_pct != null ? `${p.return_pct}%` : "—"}</td>
                  <td>
                    <button
                      className="view-btn"
                      onClick={(e) => { e.stopPropagation(); setOrderModal({ ticker: p.ticker, name: p.name }); }}
                    >
                      交易
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="paper-order-panel">
        <div className="search-bar" ref={wrapperRef} style={{ position: "relative" }}>
          <input
            type="text"
            placeholder="輸入代號或股名（例：2330 或 台積電）"
            value={tickerInput}
            onChange={handleTickerChange}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            autoComplete="off"
          />
          {showSuggestions && (
            <ul className="search-suggestions">
              {suggestions.map((s) => (
                <li key={s.ticker} onMouseDown={() => pickTicker(s.ticker)}>
                  <span className="sug-ticker">{s.ticker}</span>
                  <span className="sug-name">{s.name}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {selected && (
          <div className="paper-order-form">
            <div className="paper-order-quote">
              <span className="ticker-badge">{selected.ticker}</span>
              <span>{selected.name}</span>
              <span className="price">{selected.price} 元</span>
            </div>

            <div className="paper-side-tabs">
              <button className={side === "buy" ? "active" : ""} onClick={() => setSide("buy")}>買進</button>
              <button className={side === "sell" ? "active" : ""} onClick={() => setSide("sell")}>賣出</button>
            </div>

            <label className="paper-lots-label">
              張數（1 張 = 1000 股）
              <input
                type="number"
                min="1"
                step="1"
                value={lots}
                onChange={(e) => setLots(e.target.value)}
              />
            </label>

            <div className="paper-order-preview">
              <span>金額 {gross.toLocaleString()} 元</span>
              <span>手續費 {fee.toLocaleString()} 元</span>
              {side === "sell" && <span>證交稅（當沖減半） {tax.toLocaleString()} 元</span>}
              <span>{side === "buy" ? "預估扣款" : "預估入帳"} {Math.round(estNet).toLocaleString()} 元</span>
            </div>

            <button className="detail-btn" onClick={handleSubmit} disabled={submitting}>
              {submitting ? "送出中..." : side === "buy" ? "送出買單" : "送出賣單"}
            </button>
          </div>
        )}

        {formError && <p className="error">{formError}</p>}
        {formMsg && <p className="paper-form-msg">{formMsg}</p>}
      </div>

      <h3 className="paper-section-title">交易績效</h3>
      {!performance || performance.total_trades === 0 ? (
        <p className="no-data">尚無已平倉交易，賣出後才會累積績效統計</p>
      ) : (
        <>
          <div className="info-grid paper-summary">
            <div className="info-item">
              <span className="info-label">已平倉交易次數</span>
              <span className="info-value">{performance.total_trades}</span>
            </div>
            <div className="info-item">
              <span className="info-label">勝率</span>
              <span className="info-value">{performance.win_rate}%（{performance.win_count}勝{performance.loss_count}敗）</span>
            </div>
            <div className="info-item">
              <span className="info-label">平均獲利</span>
              <span className="info-value up">{performance.avg_win != null ? performance.avg_win.toLocaleString() : "—"}</span>
            </div>
            <div className="info-item">
              <span className="info-label">平均虧損</span>
              <span className="info-value down">{performance.avg_loss != null ? performance.avg_loss.toLocaleString() : "—"}</span>
            </div>
            <div className="info-item">
              <span className="info-label">損益比</span>
              <span className="info-value">{performance.profit_factor ?? "—"}</span>
            </div>
            <div className="info-item">
              <span className="info-label">累計已實現損益</span>
              <span className={`info-value ${performance.total_realized_pl > 0 ? "up" : performance.total_realized_pl < 0 ? "down" : ""}`}>
                {performance.total_realized_pl.toLocaleString()}
              </span>
            </div>
          </div>

          {performance.curve.length > 1 && (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={performance.curve}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) => {
                    const [, m, d] = v.split("-");
                    return `${parseInt(m)}/${parseInt(d)}`;
                  }}
                  interval="preserveStartEnd"
                />
                <YAxis tick={{ fontSize: 11 }} width={60} />
                <Tooltip
                  formatter={(v) => [v.toLocaleString(), "累計已實現損益"]}
                  labelFormatter={(l) => {
                    const [y, m, d] = l.split("-");
                    return `${y}年${parseInt(m)}月${parseInt(d)}日`;
                  }}
                />
                <Line type="monotone" dataKey="cumulative_pl" stroke="#2563eb" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </>
      )}

      <h3 className="paper-section-title">歷史成交紀錄</h3>
      {orders.length === 0 ? (
        <p className="no-data">{loading ? "載入中..." : "尚無成交紀錄"}</p>
      ) : (
        <div className="ranking-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                <th>時間</th><th>代號</th><th>名稱</th><th>買賣</th><th>股數</th>
                <th>成交價</th><th>手續費</th><th>證交稅</th><th>金額</th><th>已實現損益</th>
              </tr>
            </thead>
            <tbody>
              {pagedOrders.map((o, i) => {
                const isDeposit = o.side === "deposit";
                return (
                  <tr key={i}>
                    <td>{new Date(o.created_at * 1000).toLocaleString("zh-TW", { hour12: false })}</td>
                    <td className="col-ticker">{isDeposit ? "—" : o.ticker}</td>
                    <td className="col-name">{isDeposit ? "入金" : (o.name ?? "—")}</td>
                    <td className={isDeposit ? "" : o.side === "buy" ? "deviation-up" : "deviation-down"}>
                      {isDeposit ? "入金" : o.side === "buy" ? "買進" : "賣出"}
                    </td>
                    <td>{isDeposit ? "—" : o.qty.toLocaleString()}</td>
                    <td>{isDeposit ? "—" : o.price}</td>
                    <td>{isDeposit ? "—" : o.fee}</td>
                    <td>{isDeposit ? "—" : o.tax}</td>
                    <td>{o.net_amount.toLocaleString()}</td>
                    <td>{o.realized_pl != null ? o.realized_pl.toLocaleString() : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination page={ordersCurPage} totalPages={ordersTotalPages} onChange={setOrdersPage} />
        </div>
      )}

      {orderModal && (
        <PaperOrderModal
          ticker={orderModal.ticker}
          name={orderModal.name}
          initialSide="sell"
          placeOrder={placeDaytradePaperOrder}
          taxRate={DAY_TRADE_TAX_RATE}
          onClose={() => setOrderModal(null)}
          onSuccess={(d) => {
            setFormMsg(`${d.side === "buy" ? "買進" : "賣出"} ${d.ticker} ${d.qty / 1000} 張成交，成交價 ${d.price} 元`);
            setFormError("");
            loadAll();
          }}
        />
      )}
    </div>
  );
});

export default DaytradePaperTrading;
