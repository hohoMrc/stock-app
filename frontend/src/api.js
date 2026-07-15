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
export const scanMaSqueeze   = (limit = 200) => api.get("/api/stocks/scan/ma-squeeze",  { params: { limit } });
export const scanNearEma60   = (limit = 500) => api.get("/api/stocks/scan/near-ema60", { params: { limit } });
export const scanVolumeBreakout = (limit = 200) => api.get("/api/stocks/scan/volume-breakout", { params: { limit } });
export const scanInstitutionalBuying = (minDays = 3, limit = 200) => api.get("/api/stocks/scan/institutional-buying", { params: { min_days: minDays, limit } });
export const getIndustryStocks = (industry, exclude) =>
  api.get(`/api/stocks/industry/${encodeURIComponent(industry)}`, { params: { exclude } });
export const getTradeValueRanking = (limit = 50, force = false) => api.get("/api/stocks/ranking/trade-value", { params: { limit, force } });
export const getTurnoverRanking   = (limit = 50, force = false) => api.get("/api/stocks/ranking/turnover",     { params: { limit, force } });
export const getMoversRanking     = (direction = "up", limit = 50, force = false) => api.get("/api/stocks/ranking/movers", { params: { direction, limit, force } });
export const getWatchlistQuotes   = (tickers = []) => api.get("/api/stocks/watchlist-quotes", { params: { tickers: tickers.join(",") } });
export const getOrderbook         = (ticker)     => api.get(`/api/stocks/${ticker}/orderbook`);

// 台指期
export const getFuturesQuote         = (product = "TXF")                  => api.get("/api/futures/quote",         { params: { product } });
export const getFuturesCandles       = (timeframe = "60", product = "TXF") => api.get("/api/futures/candles",        { params: { timeframe, product } });
export const getFuturesInstitutional = ()                                   => api.get("/api/futures/institutional");
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

// 模擬下單
export const getPaperAccount   = ()                          => api.get("/api/paper/account");
export const getPaperPositions = ()                          => api.get("/api/paper/positions");
export const getPaperOrders    = (limit = 50)                => api.get("/api/paper/orders", { params: { limit } });
export const placePaperOrder   = (ticker, side, lots, price)  => api.post("/api/paper/order", { ticker, side, lots, ...(price != null ? { price } : {}) });
export const depositPaperCash  = ()                          => api.post("/api/paper/deposit");
