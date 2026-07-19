import { useState } from "react";
import { createAlert, updateAlert } from "../api";

const SCAN_OPTIONS = [
  { key: "bird_beak", label: "鳥嘴與分歧" },
  { key: "near_ema60", label: "EMA60近線" },
  { key: "volume_breakout", label: "量價突破" },
  { key: "institutional_buying", label: "法人連買" },
];

export default function AlertModal({ ticker, name, editAlert = null, onClose, onSuccess }) {
  const isEdit = !!editAlert;
  const [alertType, setAlertType] = useState(editAlert?.alert_type ?? "price_above"); // "price_above" | "price_below" | "scan_signal"
  const [targetPrice, setTargetPrice] = useState(editAlert?.target_price != null ? String(editAlert.target_price) : "");
  const [scanType, setScanType] = useState(editAlert?.scan_type ?? SCAN_OPTIONS[0].key);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (alertType !== "scan_signal" && (!targetPrice || Number(targetPrice) <= 0)) {
      setError("請輸入有效價格");
      return;
    }
    setSubmitting(true);
    try {
      if (isEdit) {
        await updateAlert(editAlert.id, {
          target_price: alertType !== "scan_signal" ? Number(targetPrice) : undefined,
          scan_type: alertType === "scan_signal" ? scanType : undefined,
        });
      } else {
        await createAlert({
          ticker,
          alert_type: alertType,
          target_price: alertType !== "scan_signal" ? Number(targetPrice) : undefined,
          scan_type: alertType === "scan_signal" ? scanType : undefined,
        });
      }
      onSuccess?.();
      onClose();
    } catch (e) {
      setError(e.response?.data?.detail || (isEdit ? "更新提醒失敗" : "建立提醒失敗"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box watch-note-modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="watch-note-title">{isEdit ? "編輯提醒" : "設定提醒"} — {ticker}{name ? ` ${name}` : ""}</h3>
        <form onSubmit={handleSubmit} className="auth-form">
          <div className="paper-side-tabs">
            <button
              type="button"
              className={alertType === "price_above" ? "active" : ""}
              onClick={() => setAlertType("price_above")}
              disabled={isEdit}
            >
              價格 ≥
            </button>
            <button
              type="button"
              className={alertType === "price_below" ? "active" : ""}
              onClick={() => setAlertType("price_below")}
              disabled={isEdit}
            >
              價格 ≤
            </button>
            <button
              type="button"
              className={alertType === "scan_signal" ? "active" : ""}
              onClick={() => setAlertType("scan_signal")}
              disabled={isEdit}
            >
              技術訊號
            </button>
          </div>

          {alertType !== "scan_signal" ? (
            <input
              type="number"
              step="0.01"
              placeholder="目標價格"
              value={targetPrice}
              onChange={(e) => setTargetPrice(e.target.value)}
              autoFocus
            />
          ) : (
            <select value={scanType} onChange={(e) => setScanType(e.target.value)}>
              {SCAN_OPTIONS.map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </select>
          )}

          {error && <p className="auth-error">{error}</p>}

          <div className="watch-note-actions">
            <button type="button" className="logout-btn" onClick={onClose}>取消</button>
            <button type="submit" className="auth-submit" disabled={submitting}>
              {submitting ? "送出中..." : isEdit ? "更新提醒" : "建立提醒"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
