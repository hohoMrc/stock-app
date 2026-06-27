import { useState } from "react";
import { login, register } from "../api";

export default function AuthModal({ onSuccess, onClose }) {
  const [mode, setMode]       = useState("login"); // "login" | "register"
  const [email, setEmail]     = useState("");
  const [password, setPass]   = useState("");
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const fn  = mode === "login" ? login : register;
      const res = await fn(email, password);
      localStorage.setItem("token", res.data.token);
      localStorage.setItem("userEmail", res.data.email);
      onSuccess(res.data.email);
    } catch (err) {
      setError(err.response?.data?.detail || "發生錯誤，請稍後再試");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-tabs">
          <button className={mode === "login" ? "active" : ""} onClick={() => { setMode("login"); setError(""); }}>登入</button>
          <button className={mode === "register" ? "active" : ""} onClick={() => { setMode("register"); setError(""); }}>註冊</button>
        </div>

        <form onSubmit={submit} className="auth-form">
          <input
            type="email" placeholder="Email" required
            value={email} onChange={(e) => setEmail(e.target.value)}
          />
          <input
            type="password" placeholder="密碼（至少 6 個字元）" required
            value={password} onChange={(e) => setPass(e.target.value)}
          />
          {error && <p className="auth-error">{error}</p>}
          <button type="submit" disabled={loading} className="auth-submit">
            {loading ? "處理中..." : mode === "login" ? "登入" : "註冊"}
          </button>
        </form>
      </div>
    </div>
  );
}
