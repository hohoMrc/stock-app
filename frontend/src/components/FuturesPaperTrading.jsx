import { useState, useEffect, forwardRef, useImperativeHandle } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import {
  getFuturesQuote, getFuturesPaperAccount, getFuturesPaperPositions, getFuturesPaperOrders,
  placeFuturesOrder, depositFuturesCash, getFuturesPaperPerformance,
  createSmartOrder, getSmartOrders, cancelSmartOrder,
} from "../api";
import Pagination, { PAGE_SIZE } from "./Pagination";

const PRODUCT_LABEL = { TXF: "大台指", TMF: "微台指" };
const TRADE_LABEL = { buy: "買進", sell: "賣出" };
const SMART_STATUS_LABEL = { pending: "待觸發", triggered: "已成交", failed: "失敗", cancelled: "已取消" };

// 重新整理/入金按鈕跟「模擬下單」標題放同一列（在 PaperTrading.jsx 的頁首），
// 用 ref 把 refresh/deposit 動作往上暴露；loading/depositing 狀態則直接由父層擁有並傳入，
// 這樣按鈕文字/disabled 狀態才能跟這個分頁實際的載入狀態同步。
const FuturesPaperTrading = forwardRef(function FuturesPaperTrading(
  { username, onRequireLogin, loading, setLoading, setDepositing },
  ref
) {
  const [account, setAccount]     = useState(null);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders]       = useState([]);
  const [performance, setPerformance] = useState(null);

  // 下單表單
  const [product]                 = useState("TMF"); // 大台指模擬下單暫時關閉，先只開放微台指
  const [quote, setQuote]         = useState(null);
  const [side, setSide]           = useState("buy");
  const [qty, setQty]             = useState(1);
  const [priceMode, setPriceMode] = useState("market"); // "market" | "custom"
  const [customPrice, setCustomPrice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [formMsg, setFormMsg]     = useState("");

  // 智慧單表單
  const [smartOrders, setSmartOrders]     = useState([]);
  const [smartProduct]                    = useState("TMF"); // 大台指模擬下單暫時關閉，先只開放微台指
  const [smartSide, setSmartSide]         = useState("buy");
  const [smartQty, setSmartQty]           = useState(1);
  const [smartTrigger, setSmartTrigger]   = useState("");
  const [smartOrderType, setSmartOrderType] = useState("stop"); // "stop" | "limit"
  const [smartSubmitting, setSmartSubmitting] = useState(false);
  const [smartError, setSmartError]       = useState("");
  const [smartMsg, setSmartMsg]           = useState("");
  const [smartOrdersPage, setSmartOrdersPage] = useState(1);
  const [ordersPage, setOrdersPage]       = useState(1);
  const [isMobile, setIsMobile] = useState(() => window.matchMedia("(max-width: 640px)").matches);

  // 手機版畫面太窄，智慧單（觸價單）列表一頁顯示 3 筆就好，不然要一直往下滑
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 640px)");
    const handler = (e) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  const smartPageSize = isMobile ? 3 : PAGE_SIZE;

  const loadAll = async () => {
    setLoading(true);
    try {
      const [accRes, posRes, ordRes, perfRes, smartRes] = await Promise.all([
        getFuturesPaperAccount(), getFuturesPaperPositions(), getFuturesPaperOrders(50), getFuturesPaperPerformance(),
        getSmartOrders(),
      ]);
      setAccount(accRes.data);
      setPositions(posRes.data.positions);
      setOrders(ordRes.data.orders);
      setPerformance(perfRes.data);
      setSmartOrders(smartRes.data.orders);
    } catch {
      // 未登入或載入失敗時保持空白，不額外報錯打擾使用者
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (username) loadAll();
  }, [username]);

  // 商品切換時抓一次即時報價，供下單面板顯示參考價
  useEffect(() => {
    let alive = true;
    getFuturesQuote(product)
      .then((res) => { if (alive) setQuote(res.data); })
      .catch(() => { if (alive) setQuote(null); });
    return () => { alive = false; };
  }, [product]);

  const handleSubmit = async () => {
    if (!username) { onRequireLogin(); return; }
    if (!qty || qty <= 0) { setFormError("口數需大於 0"); return; }
    if (priceMode === "custom" && (!customPrice || Number(customPrice) <= 0)) {
      setFormError("請輸入有效價格");
      return;
    }
    setSubmitting(true);
    setFormError("");
    setFormMsg("");
    try {
      const sendPrice = priceMode === "custom" ? Number(customPrice) : undefined;
      const res = await placeFuturesOrder(product, side, Number(qty), sendPrice);
      const d = res.data;
      const parts = [];
      if (d.closed_qty > 0) {
        const closeVerb = d.side === "buy" ? "回補空單" : "賣出多單";
        parts.push(`${closeVerb} ${d.closed_qty} 口` + (d.realized_pl != null ? `（實現損益 ${d.realized_pl.toLocaleString()}）` : ""));
      }
      if (d.opened_qty > 0) {
        const openVerb = d.side === "buy" ? "做多" : "做空";
        parts.push(`${d.closed_qty > 0 ? "並反手" : ""}${openVerb} ${d.opened_qty} 口`);
      }
      setFormMsg(`${PRODUCT_LABEL[d.product]} ${parts.join("，")}，成交價 ${d.price}`);
      setQty(1);
      setPriceMode("market");
      setCustomPrice("");
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
      const res = await depositFuturesCash();
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

  const handleSmartSubmit = async () => {
    if (!smartQty || smartQty <= 0) { setSmartError("口數需大於 0"); return; }
    if (!smartTrigger || smartTrigger <= 0) { setSmartError("觸發指數需大於 0"); return; }
    setSmartSubmitting(true);
    setSmartError("");
    setSmartMsg("");
    try {
      const res = await createSmartOrder(smartProduct, smartSide, Number(smartQty), Number(smartTrigger), smartOrderType);
      const d = res.data;
      const fillNote = d.order_type === "limit" ? `以 ${d.trigger_price} 成交` : "用當下市價成交";
      setSmartMsg(`已設定：指數${d.direction === "above" ? "漲到" : "跌到"} ${d.trigger_price} 時自動${TRADE_LABEL[d.side]}，${fillNote}`);
      setSmartTrigger("");
      setSmartOrderType("stop");
      loadAll();
    } catch (e) {
      setSmartError(e.response?.data?.detail || "設定失敗");
    } finally {
      setSmartSubmitting(false);
    }
  };

  const handleSmartCancel = async (orderId) => {
    try {
      await cancelSmartOrder(orderId);
      loadAll();
    } catch (e) {
      setSmartError(e.response?.data?.detail || "取消失敗");
    }
  };

  if (!username) {
    return (
      <div>
        <p className="no-data">請先登入才能使用期貨模擬下單功能</p>
        <button className="login-btn" onClick={onRequireLogin}>登入 / 註冊</button>
      </div>
    );
  }

  const smartOrdersTotalPages = Math.max(1, Math.ceil(smartOrders.length / smartPageSize));
  const smartOrdersCurPage    = Math.min(smartOrdersPage, smartOrdersTotalPages);
  const pagedSmartOrders      = smartOrders.slice((smartOrdersCurPage - 1) * smartPageSize, smartOrdersCurPage * smartPageSize);

  const ordersTotalPages = Math.max(1, Math.ceil(orders.length / PAGE_SIZE));
  const ordersCurPage    = Math.min(ordersPage, ordersTotalPages);
  const pagedOrders      = orders.slice((ordersCurPage - 1) * PAGE_SIZE, ordersCurPage * PAGE_SIZE);

  return (
    <div>

      <p className="ranking-hint">
        期貨保證金帳戶跟股票模擬下單分開計算。原始保證金/手續費用約略值僅供模擬參考，
        不會模擬每日結算強制平倉。
      </p>

      {account && (
        <div className="info-grid paper-summary">
          <div className="info-item">
            <span className="info-label">現金</span>
            <span className="info-value">{account.cash.toLocaleString()}</span>
          </div>
          <div className="info-item">
            <span className="info-label">已用保證金</span>
            <span className="info-value">{account.used_margin.toLocaleString()}</span>
          </div>
          <div className="info-item">
            <span className="info-label">可用保證金</span>
            <span className="info-value">{account.available_margin.toLocaleString()}</span>
          </div>
          <div className="info-item">
            <span className="info-label">未實現損益</span>
            <span className={`info-value ${account.unrealized_pl > 0 ? "up" : account.unrealized_pl < 0 ? "down" : ""}`}>
              {account.unrealized_pl.toLocaleString()}
            </span>
          </div>
          <div className="info-item">
            <span className="info-label">淨值</span>
            <span className="info-value">{account.equity.toLocaleString()}</span>
          </div>
        </div>
      )}

      <h3 className="paper-section-title">持倉</h3>
      {positions.length === 0 ? (
        <p className="no-data">{loading ? "載入中..." : "目前無持倉"}</p>
      ) : (
        <div className="ranking-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                <th>商品</th><th>方向</th><th>口數</th><th>均價</th><th>現價</th>
                <th>保證金</th><th>未實現損益</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.product} className={p.unrealized_pl > 0 ? "row-up" : p.unrealized_pl < 0 ? "row-down" : ""}>
                  <td className="col-ticker">{PRODUCT_LABEL[p.product]}</td>
                  <td>{p.side === "long" ? "多" : "空"}</td>
                  <td>{p.qty}</td>
                  <td>{p.avg_price}</td>
                  <td>{p.price ?? "—"}</td>
                  <td>{p.margin.toLocaleString()}</td>
                  <td>{p.unrealized_pl?.toLocaleString() ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="paper-order-panel">
        <div className="paper-side-tabs">
          {/* 大台指模擬下單暫時關閉，先只開放微台指 */}
          <button className="active">微台指</button>
        </div>

        <div className="paper-order-form">
          <div className="paper-order-quote">
            <span className="ticker-badge">{product}</span>
            <span>{quote?.name ?? PRODUCT_LABEL[product]}</span>
            <span className="price">{quote?.price ?? "—"} 點</span>
          </div>

          <div className="paper-side-tabs">
            <button
              className={side === "buy" ? "active" : ""}
              onClick={() => setSide("buy")}
              title="多單加碼、空單回補；回補口數超過空單口數會反手做多"
            >
              買
            </button>
            <button
              className={side === "sell" ? "active" : ""}
              onClick={() => setSide("sell")}
              title="空單加碼、多單賣出；賣出口數超過多單口數會反手做空"
            >
              賣
            </button>
          </div>

          <div className="paper-side-tabs">
            <button className={priceMode === "market" ? "active" : ""} onClick={() => setPriceMode("market")}>市價</button>
            <button className={priceMode === "custom" ? "active" : ""} onClick={() => setPriceMode("custom")}>指定價格</button>
          </div>

          {priceMode === "custom" && (
            <label className="paper-lots-label">
              價格（模擬用，送出後直接以這個價格記帳成交，不是真的掛單等成交）
              <input
                type="number"
                step="1"
                value={customPrice}
                onChange={(e) => setCustomPrice(e.target.value)}
              />
            </label>
          )}

          <label className="paper-lots-label">
            口數
            <input
              type="number"
              min="1"
              step="1"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
            />
          </label>

          <button className="detail-btn" onClick={handleSubmit} disabled={submitting}>
            {submitting ? "送出中..." : `送出${TRADE_LABEL[side]}單`}
          </button>
        </div>

        {formError && <p className="error">{formError}</p>}
        {formMsg && <p className="paper-form-msg">{formMsg}</p>}
      </div>

      <h3 className="paper-section-title">智慧單（到價自動下單）</h3>
      <p className="ranking-hint">
        設定指數到多少自動成交，不用一直盯盤。系統每 2 分鐘檢查一次，觸價後用當下市價成交
        （不保證剛好成交在設定的價位，跟真實停損/停利單一樣）。
      </p>
      <div className="paper-order-panel">
        <div className="paper-side-tabs">
          {/* 大台指模擬下單暫時關閉，先只開放微台指 */}
          <button className="active">微台指</button>
        </div>
        <div className="paper-side-tabs">
          <button
            className={smartSide === "buy" ? "active" : ""}
            onClick={() => setSmartSide("buy")}
            title="多單加碼、空單回補；回補口數超過空單口數會反手做多"
          >
            買
          </button>
          <button
            className={smartSide === "sell" ? "active" : ""}
            onClick={() => setSmartSide("sell")}
            title="空單加碼、多單賣出；賣出口數超過多單口數會反手做空"
          >
            賣
          </button>
        </div>
        <label className="paper-lots-label">
          口數
          <input type="number" min="1" step="1" value={smartQty} onChange={(e) => setSmartQty(e.target.value)} />
        </label>
        <label className="paper-lots-label">
          觸發指數
          <input type="number" step="1" value={smartTrigger} onChange={(e) => setSmartTrigger(e.target.value)} />
        </label>
        <div className="paper-side-tabs">
          <button
            className={smartOrderType === "stop" ? "active" : ""}
            onClick={() => setSmartOrderType("stop")}
            title="觸價後用當下市價成交，可能有滑價，跟真實停損/停利單一樣"
          >
            觸價後市價成交
          </button>
          <button
            className={smartOrderType === "limit" ? "active" : ""}
            onClick={() => setSmartOrderType("limit")}
            title="觸價後直接用你設定的觸發指數成交，價格不會跑掉；但條件比較嚴格，要漲/跌到那個價位或更好才會觸發"
          >
            限價成交
          </button>
        </div>
        <button className="detail-btn" onClick={handleSmartSubmit} disabled={smartSubmitting}>
          {smartSubmitting ? "送出中..." : "設定智慧單"}
        </button>
        {smartError && <p className="error">{smartError}</p>}
        {smartMsg && <p className="paper-form-msg">{smartMsg}</p>}
      </div>

      {smartOrders.length === 0 ? (
        <p className="no-data">{loading ? "載入中..." : "尚無智慧單"}</p>
      ) : (
        <div className="ranking-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                <th>商品</th><th>買賣</th><th>口數</th><th>觸發指數</th>
                <th>狀態</th><th>備註</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {pagedSmartOrders.map((o) => (
                <tr key={o.id}>
                  <td className="col-ticker">{PRODUCT_LABEL[o.product]}</td>
                  <td>{TRADE_LABEL[o.side]}</td>
                  <td>{o.qty}</td>
                  <td>{o.trigger_price}（{o.direction === "above" ? "漲到" : "跌到"}）</td>
                  <td>{SMART_STATUS_LABEL[o.status]}</td>
                  <td>{o.status === "failed" ? o.fail_reason : "—"}</td>
                  <td>
                    {o.status === "pending" && (
                      <button className="view-btn" onClick={() => handleSmartCancel(o.id)}>取消</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination page={smartOrdersCurPage} totalPages={smartOrdersTotalPages} onChange={setSmartOrdersPage} />
        </div>
      )}

      <h3 className="paper-section-title">交易績效</h3>
      {!performance || performance.total_trades === 0 ? (
        <p className="no-data">尚無已平倉交易，平倉後才會累積績效統計</p>
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
                <th>時間</th><th>商品</th><th>方向</th><th>動作</th><th>口數</th>
                <th>成交價</th><th>手續費</th><th>期交稅</th><th>金額</th><th>已實現損益</th>
              </tr>
            </thead>
            <tbody>
              {pagedOrders.map((o, i) => {
                const isDeposit = o.action === "deposit";
                return (
                  <tr key={i}>
                    <td>{new Date(o.created_at * 1000).toLocaleString("zh-TW", { hour12: false })}</td>
                    <td className="col-ticker">{isDeposit ? "—" : PRODUCT_LABEL[o.product]}</td>
                    <td>{isDeposit ? "—" : (o.side === "long" ? "多" : "空")}</td>
                    <td>{isDeposit ? "入金" : (o.action === "open" ? "建倉" : "平倉")}</td>
                    <td>{isDeposit ? "—" : o.qty}</td>
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
    </div>
  );
});

export default FuturesPaperTrading;
