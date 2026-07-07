import axios from "axios";

const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000", timeout: 300000 });

// 自動帶入 JWT token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export const searchStocks = (q) => api.get("/api/stocks/search", { params: { q } });
export const getStock = (ticker) => api.get(`/api/stocks/${ticker}`);
export const getHistory = (ticker, period = "3mo", interval = "1d") => api.get(`/api/stocks/${ticker}/history`, { params: { period, interval } });
export const analyzeStock = (ticker) => api.get(`/api/stocks/${ticker}/analyze`);
export const screenStocks = (filters) => api.post("/api/stocks/screen", filters);
export const scanWeeklySurge = (params) => api.get("/api/stocks/scan/weekly-surge", { params });
export const scanMaSqueeze   = (limit = 200) => api.get("/api/stocks/scan/ma-squeeze", { params: { limit } });
export const getIndustryStocks = (industry, exclude) =>
  api.get(`/api/stocks/industry/${encodeURIComponent(industry)}`, { params: { exclude } });
export const getTradeValueRanking = (limit = 50, force = false) => api.get("/api/stocks/ranking/trade-value", { params: { limit, force } });
export const getTurnoverRanking   = (limit = 50, force = false) => api.get("/api/stocks/ranking/turnover",     { params: { limit, force } });
export const getOrderbook         = (ticker)     => api.get(`/api/stocks/${ticker}/orderbook`);

// 台指期
export const getFuturesQuote         = (symbol)        => api.get("/api/futures/quote",         { params: symbol ? { symbol } : {} });
export const getFuturesCandles       = (timeframe = "60", symbol) => api.get("/api/futures/candles", { params: { timeframe, ...(symbol ? { symbol } : {}) } });
export const getFuturesInstitutional = ()               => api.get("/api/futures/institutional");
export const getTrades            = (ticker, limit = 30) => api.get(`/api/stocks/${ticker}/trades`, { params: { limit } });

// Auth
export const register = (username, password) => api.post("/api/auth/register", { username, password });
export const login    = (username, password) => api.post("/api/auth/login",    { username, password });

// Admin
export const adminListUsers        = ()                        => api.get("/api/admin/users");
export const adminChangePassword   = (userId, new_password)    => api.patch(`/api/admin/users/${userId}/password`, { new_password });
export const adminDeleteUser       = (userId)                  => api.delete(`/api/admin/users/${userId}`);

// Watchlist（後端版）
export const fetchWatchlist   = ()                => api.get("/api/watchlist");
export const addWatch         = (ticker)          => api.post(`/api/watchlist/${ticker}`);
export const removeWatch      = (ticker)          => api.delete(`/api/watchlist/${ticker}`);
export const updateWatchNote  = (ticker, note)    => api.patch(`/api/watchlist/${ticker}/note`, { note });
