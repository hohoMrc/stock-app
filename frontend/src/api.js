import axios from "axios";

const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000", timeout: 300000 }); // 最長等 5 分鐘

export const searchStocks = (q) => api.get("/api/stocks/search", { params: { q } });
export const getStock = (ticker) => api.get(`/api/stocks/${ticker}`);
export const getHistory = (ticker, period = "3mo", interval = "1d") => api.get(`/api/stocks/${ticker}/history`, { params: { period, interval } });
export const analyzeStock = (ticker) => api.get(`/api/stocks/${ticker}/analyze`);
export const screenStocks = (filters) => api.post("/api/stocks/screen", filters);
export const scanWeeklySurge = (params) => api.get("/api/stocks/scan/weekly-surge", { params });
export const getIndustryStocks = (industry, exclude) =>
  api.get(`/api/stocks/industry/${encodeURIComponent(industry)}`, { params: { exclude } });
