import { useState, useEffect, useRef } from "react";
import { searchStocks, getStock, getPaperAccount, getPaperPositions, getPaperOrders, placePaperOrder, depositPaperCash } from "../api";

export default function PaperTrading({ username, onRequireLogin }) {
  const [account, setAccount]     = useState(null);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders]       = useState([]);
  const [loading, setLoading]     = useState(false);

  // 下單表單
  const [tickerInput, setTickerInput] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selected, setSelected]       = useState(null); // { ticker, name, price }
  const [side, setSide]               = useState("buy");
  const [lots, setLots]               = useState(1);
  const [submitting, setSubmitting]   = useState(false);
  const [formError, setFormError]     = useState("");
  const [formMsg, setFormMsg]         = useState("");
  const [depositing, setDepositing]   = useState(false);

  const debounceRef = useRef(null);
  const wrapperRef  = useRef(null);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [accRes, posRes, ordRes] = await Promise.all([
        getPaperAccount(), getPaperPositions(), getPaperOrders(50),
      ]);
      setAccount(accRes.data);
      setPositions(posRes.data.positions);
      setOrders(ordRes.data.orders);
    } catch {
      // 未登入或載入失敗時保持空白，不额外報錯打擾使用者
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
      const res = await placePaperOrder(selected.ticker, side, Number(lots));
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
      await depositPaperCash();
      setFormMsg("已入金 100,000 元");
      setFormError("");
      loadAll();
    } catch (e) {
      setFormError(e.response?.data?.detail || "入金失敗");
    } finally {
      setDepositing(false);
    }
  };

  if (!username) {
    return (
      <div className="page">
        <h2>模擬下單</h2>
        <p className="no-data">請先登入才能使用模擬下單功能</p>
        <button className="login-btn" onClick={onRequireLogin}>登入 / 註冊</button>
      </div>
    );
  }

  const gross = selected ? selected.price * lots * 1000 : 0;
  const fee   = gross ? Math.max(Math.round(gross * 0.001425), 20) : 0;
  const tax   = side === "sell" && gross ? Math.round(gross * 0.003) : 0;
  const estNet = side === "buy" ? gross + fee : gross - fee - tax;

  return (
    <div className="page paper-page">
      <div className="paper-page-header">
        <h2>模擬下單</h2>
        <button className="deposit-btn" onClick={handleDeposit} disabled={depositing}>
          {depositing ? "入金中..." : "入金 10 萬"}
        </button>
      </div>

      {account && (
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
              {side === "sell" && <span>證交稅 {tax.toLocaleString()} 元</span>}
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

      <h3 className="paper-section-title">持股</h3>
      {positions.length === 0 ? (
        <p className="no-data">{loading ? "載入中..." : "目前無持股"}</p>
      ) : (
        <div className="ranking-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                <th>代號</th><th>名稱</th><th>張數</th><th>均價</th><th>現價</th>
                <th>市值</th><th>未實現損益</th><th>報酬率</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.ticker} className={p.unrealized_pl > 0 ? "row-up" : p.unrealized_pl < 0 ? "row-down" : ""}>
                  <td className="col-ticker">{p.ticker}</td>
                  <td className="col-name">{p.name ?? "—"}</td>
                  <td>{p.lots}</td>
                  <td>{p.avg_cost}</td>
                  <td>{p.price ?? "—"}</td>
                  <td>{p.market_value?.toLocaleString() ?? "—"}</td>
                  <td>{p.unrealized_pl?.toLocaleString() ?? "—"}</td>
                  <td>{p.return_pct != null ? `${p.return_pct}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
              {orders.map((o, i) => {
                const isDeposit = o.side === "deposit";
                return (
                  <tr key={i}>
                    <td>{new Date(o.created_at * 1000).toLocaleString("zh-TW", { hour12: false })}</td>
                    <td className="col-ticker">{isDeposit ? "—" : o.ticker}</td>
                    <td className="col-name">{isDeposit ? "入金" : (o.name ?? "—")}</td>
                    <td>{isDeposit ? "入金" : o.side === "buy" ? "買進" : "賣出"}</td>
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
        </div>
      )}
    </div>
  );
}
