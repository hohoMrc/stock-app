import { useState, useEffect } from "react";
import { getAlerts, deleteAlert } from "../api";
import AlertModal from "./AlertModal";

const SCAN_LABEL = {
  bird_beak: "鳥嘴與分歧",
  near_ema60: "EMA60近線",
  volume_breakout: "量價突破",
  institutional_buying: "法人連買",
};

function describeCondition(a) {
  if (a.alert_type === "price_above") return `價格 ≥ ${a.target_price} 元`;
  if (a.alert_type === "price_below") return `價格 ≤ ${a.target_price} 元`;
  return `${SCAN_LABEL[a.scan_type] ?? a.scan_type} 訊號`;
}

export default function AlertsPage({ username, onRequireLogin, onSelect }) {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editingAlert, setEditingAlert] = useState(null);

  const load = () => {
    setLoading(true);
    setError(null);
    getAlerts()
      .then((res) => setAlerts(res.data.alerts || []))
      .catch((e) => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { if (username) load(); }, [username]);

  const handleDelete = async (id) => {
    try {
      await deleteAlert(id);
      setAlerts((prev) => prev.filter((a) => a.id !== id));
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  };

  if (!username) {
    return (
      <div className="page">
        <h2>提醒</h2>
        <p className="no-data">請先登入才能使用個人化提醒功能</p>
        <button className="login-btn" onClick={onRequireLogin}>登入 / 註冊</button>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="watchlist-header-row">
        <h2>提醒</h2>
      </div>

      {error && <p className="error">❌ {error}</p>}

      {loading ? (
        <p className="loading-hint">載入中...</p>
      ) : alerts.length === 0 ? (
        <div className="empty-watchlist">
          <p>尚未設定任何提醒</p>
          <p className="empty-hint">在個股頁點擊「🔔 設定提醒」建立</p>
        </div>
      ) : (
        <table className="result-table">
          <thead>
            <tr>
              <th>代號</th>
              <th>條件</th>
              <th>狀態</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr key={a.id}>
                <td>{a.ticker}</td>
                <td>{describeCondition(a)}</td>
                <td>
                  {a.active
                    ? "監控中"
                    : `已於 ${new Date(a.triggered_at * 1000).toLocaleString("zh-TW", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })} 觸發`}
                </td>
                <td className="watchlist-actions">
                  {onSelect && <button className="view-btn" onClick={() => onSelect(a.ticker)}>查看</button>}
                  <button className="view-btn" onClick={() => setEditingAlert(a)}>編輯</button>
                  <button className="remove-btn" onClick={() => handleDelete(a.id)}>移除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {editingAlert && (
        <AlertModal
          ticker={editingAlert.ticker}
          name=""
          editAlert={editingAlert}
          onClose={() => setEditingAlert(null)}
          onSuccess={load}
        />
      )}
    </div>
  );
}
