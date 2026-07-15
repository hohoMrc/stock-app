import { useState, useEffect, useRef } from "react";
import { getOrderbook, placePaperOrder } from "../api";
import { calcFee, calcTax } from "../feeCalc";

export default function PaperOrderModal({ ticker, name, initialSide = "sell", onClose, onSuccess }) {
  const [side, setSide]           = useState(initialSide);
  const [orderbook, setOrderbook] = useState({ best_bids: [], best_asks: [] });
  const [marketPrice, setMarketPrice] = useState(null);
  const [priceMode, setPriceMode] = useState("market"); // "market" | "limit"
  const [price, setPrice]         = useState("");
  const [lots, setLots]           = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError]         = useState("");
  const pollRef = useRef(null);

  useEffect(() => {
    let alive = true;
    const fetchOb = async () => {
      try {
        const res = await getOrderbook(ticker);
        if (!alive) return;
        setOrderbook(res.data);
        if (res.data.close != null) setMarketPrice(res.data.close);
      } catch { /* ignore，保留上次資料 */ }
    };
    fetchOb();
    pollRef.current = setInterval(fetchOb, 5000);
    return () => { alive = false; clearInterval(pollRef.current); };
  }, [ticker]);

  const pickPrice = (p) => {
    setPriceMode("limit");
    setPrice(String(p));
  };

  const effectivePrice = priceMode === "market" ? marketPrice : Number(price);
  const gross  = effectivePrice ? effectivePrice * Number(lots || 0) * 1000 : 0;
  const fee    = gross ? calcFee(gross) : 0;
  const tax    = side === "sell" && gross ? calcTax(gross) : 0;
  const estNet = side === "buy" ? gross + fee : gross - fee - tax;

  const handleSubmit = async () => {
    setError("");
    if (!lots || lots <= 0) { setError("張數需大於 0"); return; }
    if (priceMode === "limit" && (!price || Number(price) <= 0)) { setError("請輸入有效價格"); return; }
    setSubmitting(true);
    try {
      const sendPrice = priceMode === "limit" ? Number(price) : undefined;
      const res = await placePaperOrder(ticker, side, Number(lots), sendPrice);
      onSuccess(res.data);
      onClose();
    } catch (e) {
      setError(e.response?.data?.detail || "下單失敗");
    } finally {
      setSubmitting(false);
    }
  };

  const asksDesc = [...(orderbook.best_asks || [])].slice(0, 5).reverse();
  const bidsDesc = (orderbook.best_bids || []).slice(0, 5);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="pom-modal" onClick={(e) => e.stopPropagation()}>
        <div className="pom-header">
          <div>
            <span className="ticker-badge">{ticker}</span>
            <span className="pom-name">{name}</span>
          </div>
          <button className="pom-close" onClick={onClose}>✕</button>
        </div>

        <div className="paper-side-tabs">
          <button className={side === "buy" ? "active" : ""} onClick={() => setSide("buy")}>買進</button>
          <button className={side === "sell" ? "active" : ""} onClick={() => setSide("sell")}>賣出</button>
        </div>

        <div className="pom-orderbook">
          <div className="pom-ob-col">
            {asksDesc.map((a, i) => (
              <div key={`ask-${i}`} className="pom-ob-row" onClick={() => pickPrice(a.price)}>
                <span className="pom-ob-price down">{a.price}</span>
                <span className="pom-ob-size">{a.size}</span>
              </div>
            ))}
          </div>
          <div className="pom-ob-mid">{marketPrice ?? "—"}</div>
          <div className="pom-ob-col">
            {bidsDesc.map((b, i) => (
              <div key={`bid-${i}`} className="pom-ob-row" onClick={() => pickPrice(b.price)}>
                <span className="pom-ob-price up">{b.price}</span>
                <span className="pom-ob-size">{b.size}</span>
              </div>
            ))}
          </div>
        </div>
        <p className="pom-ob-hint">點五檔價格可直接帶入下方指定價格</p>

        <div className="pom-price-mode">
          <button className={priceMode === "market" ? "active" : ""} onClick={() => setPriceMode("market")}>市價</button>
          <button className={priceMode === "limit" ? "active" : ""} onClick={() => setPriceMode("limit")}>指定價格</button>
        </div>

        {priceMode === "limit" && (
          <input
            className="pom-price-input"
            type="number"
            step="0.01"
            placeholder="輸入價格"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
        )}

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
          <span>價格 {effectivePrice ?? "—"} 元</span>
          <span>金額 {Math.round(gross).toLocaleString()} 元</span>
          <span>手續費 {fee.toLocaleString()} 元</span>
          {side === "sell" && <span>證交稅 {tax.toLocaleString()} 元</span>}
          <span>{side === "buy" ? "預估扣款" : "預估入帳"} {Math.round(estNet).toLocaleString()} 元</span>
        </div>

        {error && <p className="error">{error}</p>}

        <button className="detail-btn" onClick={handleSubmit} disabled={submitting || !effectivePrice}>
          {submitting ? "送出中..." : side === "buy" ? "送出買單" : "送出賣單"}
        </button>
      </div>
    </div>
  );
}
