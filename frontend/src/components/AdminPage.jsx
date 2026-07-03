import { useState, useEffect } from "react";
import { adminListUsers, adminChangePassword, adminDeleteUser } from "../api";

export default function AdminPage() {
  const [users, setUsers]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [editId, setEditId]     = useState(null);
  const [newPwd, setNewPwd]     = useState("");
  const [msg, setMsg]           = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await adminListUsers();
      setUsers(res.data.users);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleChangePwd = async (userId) => {
    if (newPwd.length < 6) { setMsg({ type: "error", text: "密碼至少 6 個字元" }); return; }
    try {
      await adminChangePassword(userId, newPwd);
      setMsg({ type: "ok", text: "密碼已更新" });
      setEditId(null);
      setNewPwd("");
    } catch (e) {
      setMsg({ type: "error", text: e?.response?.data?.detail || "更新失敗" });
    }
  };

  const handleDelete = async (userId, username) => {
    if (!confirm(`確定要刪除帳號「${username}」？`)) return;
    try {
      await adminDeleteUser(userId);
      setMsg({ type: "ok", text: `已刪除 ${username}` });
      load();
    } catch (e) {
      setMsg({ type: "error", text: e?.response?.data?.detail || "刪除失敗" });
    }
  };

  const fmtDate = (ts) => {
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleString("zh-TW", { timeZone: "Asia/Taipei" });
  };

  return (
    <div className="page">
      <h2>帳號管理</h2>

      {msg && (
        <p className={msg.type === "ok" ? "success-msg" : "error"} style={{ marginBottom: 12 }}>
          {msg.type === "ok" ? "✓ " : "✗ "}{msg.text}
        </p>
      )}

      {loading ? (
        <p className="loading-hint">載入中...</p>
      ) : users.length === 0 ? (
        <p className="no-data">目前沒有任何帳號</p>
      ) : (
        <table className="result-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>帳號</th>
              <th>建立時間</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.id}</td>
                <td><strong>{u.username}</strong></td>
                <td style={{ fontSize: "0.85em", color: "#94a3b8" }}>{fmtDate(u.created_at)}</td>
                <td>
                  {editId === u.id ? (
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <input
                        type="password"
                        placeholder="新密碼（≥6 字元）"
                        value={newPwd}
                        onChange={(e) => setNewPwd(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleChangePwd(u.id)}
                        style={{ width: 160, padding: "4px 8px", borderRadius: 4,
                                 border: "1px solid #334155", background: "#0f172a", color: "#e2e8f0" }}
                        autoFocus
                      />
                      <button className="view-btn" onClick={() => handleChangePwd(u.id)}>確認</button>
                      <button className="view-btn" style={{ background: "#334155" }}
                        onClick={() => { setEditId(null); setNewPwd(""); }}>取消</button>
                    </div>
                  ) : (
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="view-btn"
                        onClick={() => { setEditId(u.id); setNewPwd(""); setMsg(null); }}>
                        改密碼
                      </button>
                      <button className="view-btn" style={{ background: "#7f1d1d", color: "#fca5a5" }}
                        onClick={() => handleDelete(u.id, u.username)}>
                        刪除
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
