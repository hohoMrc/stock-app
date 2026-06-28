import { useState } from "react";
import { screenStocks, scanWeeklySurge } from "../api";

const DEFAULT_TICKERS = [
  // 半導體
  "2330", "2303", "2454", "3711", "2379", "2344", "2408",
  // 電子製造 / 零組件
  "2317", "2357", "2308", "2382", "2395", "3008", "2301", "2327",
  // 通訊 / 網路
  "2412", "4904", "3045",
  // 金融
  "2882", "2881", "2891", "2886", "2884",
  // 石化 / 傳產
  "1301", "1303", "1326", "2002", "1101",
  // 股金寶找到的高週漲幅個股
  "2481", "3588", "6168", "6226", "6243", "6573", "6834",
];

const EMPTY_FILTERS = {
  min_price: "", max_price: "",
  min_volume: "",
  min_market_cap: "", max_market_cap: "",
  min_capital: "",
  min_pe: "", max_pe: "",
  min_dividend_yield: "",
  min_weekly_change: "",
  near_ma: "", near_ma_pct: "3",
  pattern: "",
  custom_tickers: "",
};

const MA_OPTIONS = [
  { value: "", label: "不篩選" },
  { value: "ma5",   label: "週線 (MA5)" },
  { value: "ma20",  label: "月線 (MA20)" },
  { value: "ma60",  label: "季線 (MA60)" },
  { value: "ma240", label: "年線 (MA240)" },
  { value: "ema60", label: "EMA60 (指數移動平均)" },
];

export default function StockScreener({ onSelect, filters, setFilters, results, setResults, searched, setSearched }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // 週漲幅急漲固定條件
  const WEEKLY_SURGE_PRESET = {
    min_weekly_change: "20",  // 週漲幅 ≥ 20%
    min_volume: "1000",       // 日成交量 ≥ 1000 張
    min_capital: "2",         // 股本 ≥ 2 億元
  };

  const handleWeeklySurge = async () => {
    setLoading(true);
    setError(null);
    setResults([]);
    try {
      const res = await scanWeeklySurge({ min_weekly_change: 20, min_volume: 1000, min_capital: 2 });
      setResults(res.data.stocks);
      setSearched(true);
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.detail || e.message || "掃描失敗");
      setSearched(true);
    } finally {
      setLoading(false);
    }
  };

  const handlePattern = (pattern) => {
    // 型態篩選：清除其他條件，保留自訂股票清單
    const newFilters = { ...EMPTY_FILTERS, pattern, custom_tickers: filters.custom_tickers };
    setFilters(newFilters);
    runScreen(newFilters);
  };

  const handleScreen = () => runScreen(filters);

  const runScreen = async (f) => {
    setLoading(true);
    setError(null);
    setResults([]);
    try {
      const tickers = f.custom_tickers
        ? f.custom_tickers.split(/[,\s]+/).filter(Boolean)
        : DEFAULT_TICKERS;

      const n = (v) => v ? parseFloat(v) : null;
      const payload = {
        tickers,
        min_price: n(f.min_price), max_price: n(f.max_price),
        min_volume: n(f.min_volume),
        min_market_cap: n(f.min_market_cap), max_market_cap: n(f.max_market_cap),
        min_capital: n(f.min_capital),
        min_pe: n(f.min_pe), max_pe: n(f.max_pe),
        min_dividend_yield: n(f.min_dividend_yield),
        min_weekly_change: n(f.min_weekly_change),
        near_ma: f.near_ma || null,
        near_ma_pct: parseFloat(f.near_ma_pct) || 3,
        pattern: f.pattern || null,
      };

      const res = await screenStocks(payload);
      setResults(res.data.stocks);
      setSearched(true);
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.detail || e.message || "篩選失敗，請確認後端是否運行");
      setSearched(true);
    } finally {
      setLoading(false);
    }
  };

  const hasMA = !!filters.near_ma;
  const hasPattern = !!filters.pattern;
  const PATTERN_LABEL = { bird_beak: "🐦 鳥嘴", divergence: "↗ 分歧" };

  return (
    <div className="page">
      <h2>選股篩選</h2>

      {/* 快捷條件按鈕 */}
      <div className="preset-bar">
        <span className="preset-label">快速篩選</span>
        <button
          className="preset-btn"
          onClick={handleWeeklySurge}
          disabled={loading}
          title="週漲幅 ≥ 20% 且 日成交量 ≥ 1000 張 且 股本 ≥ 2 億"
        >
          🚀 週漲幅急漲
        </button>
        <button
          className="preset-btn preset-btn--pattern"
          onClick={() => handlePattern("bird_beak")}
          disabled={loading}
          title="MA5 從下方逼近 MA20，即將黃金交叉"
        >
          🐦 鳥嘴
        </button>
        <button
          className="preset-btn preset-btn--pattern"
          onClick={() => handlePattern("divergence")}
          disabled={loading}
          title="MA5/MA20 曾幾乎黏合，現再度分開上漲"
        >
          ↗ 分歧
        </button>
      </div>

      <div className="filter-form">
        <div className="filter-section-title">基本面條件</div>

        <div className="filter-row">
          <label>股價範圍 (元)</label>
          <div className="filter-inputs">
            <input
              type="number"
              placeholder="最低"
              value={filters.min_price}
              onChange={(e) => setFilters({ ...filters, min_price: e.target.value })}
            />
            <span>～</span>
            <input
              type="number"
              placeholder="最高"
              value={filters.max_price}
              onChange={(e) => setFilters({ ...filters, max_price: e.target.value })}
            />
          </div>
        </div>

        <div className="filter-row">
          <label>日成交量 (≥ 張)</label>
          <input
            type="number"
            placeholder="例：1000"
            value={filters.min_volume}
            onChange={(e) => setFilters({ ...filters, min_volume: e.target.value })}
          />
        </div>

        <div className="filter-row">
          <label>市值範圍 (億元)</label>
          <div className="filter-inputs">
            <input
              type="number"
              placeholder="最低"
              value={filters.min_market_cap}
              onChange={(e) => setFilters({ ...filters, min_market_cap: e.target.value })}
            />
            <span>～</span>
            <input
              type="number"
              placeholder="最高"
              value={filters.max_market_cap}
              onChange={(e) => setFilters({ ...filters, max_market_cap: e.target.value })}
            />
          </div>
        </div>

        <div className="filter-row">
          <label>本益比範圍</label>
          <div className="filter-inputs">
            <input
              type="number"
              placeholder="最小 PE"
              value={filters.min_pe}
              onChange={(e) => setFilters({ ...filters, min_pe: e.target.value })}
            />
            <span>～</span>
            <input
              type="number"
              placeholder="最大 PE"
              value={filters.max_pe}
              onChange={(e) => setFilters({ ...filters, max_pe: e.target.value })}
            />
          </div>
        </div>

        <div className="filter-row">
          <label>最低殖利率 (%)</label>
          <input
            type="number"
            placeholder="例：3"
            value={filters.min_dividend_yield}
            onChange={(e) => setFilters({ ...filters, min_dividend_yield: e.target.value })}
          />
        </div>

        <div className="filter-divider" />
        <div className="filter-section-title">線型條件</div>

        <div className="filter-row">
          <label>股價接近均線</label>
          <select
            value={filters.near_ma}
            onChange={(e) => setFilters({ ...filters, near_ma: e.target.value })}
          >
            {MA_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {hasMA && (
          <div className="filter-row">
            <label>偏離幅度 (%以內)</label>
            <div className="filter-inputs">
              <input
                type="number"
                min="0.5"
                max="20"
                step="0.5"
                value={filters.near_ma_pct}
                onChange={(e) => setFilters({ ...filters, near_ma_pct: e.target.value })}
              />
              <span className="filter-hint">
                股價在均線 ±{filters.near_ma_pct}% 以內
              </span>
            </div>
          </div>
        )}

        <div className="filter-row">
          <label>均線型態</label>
          <div className="pattern-btns">
            {[
              { value: "",            label: "不篩選" },
              { value: "bird_beak",   label: "🐦 鳥嘴", desc: "MA5 從下方逼近 MA20，即將黃金交叉" },
              { value: "divergence",  label: "↗ 分歧",  desc: "MA5/MA20 曾幾乎黏合，現再度分開上漲" },
            ].map((o) => (
              <button
                key={o.value}
                className={`pattern-btn ${filters.pattern === o.value ? "active" : ""}`}
                onClick={() => setFilters({ ...filters, pattern: o.value })}
                title={o.desc}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>

        <div className="filter-divider" />
        <div className="filter-section-title">股票範圍</div>

        <div className="filter-row">
          <label>自訂股票代號</label>
          <input
            type="text"
            placeholder="留空使用預設清單；多筆用逗號分隔（例：2330, 2317）"
            value={filters.custom_tickers}
            onChange={(e) => setFilters({ ...filters, custom_tickers: e.target.value })}
          />
        </div>

        <button className="screen-btn" onClick={handleScreen} disabled={loading}>
          {loading ? "篩選中..." : "開始篩選"}
        </button>
      </div>

      {loading && (
        <p className="loading-hint">
          正在掃描中，請稍候...（週漲幅全市場約 2 分鐘，型態分析約 40 秒）
        </p>
      )}

      {searched && !loading && error && (
        <p className="error">❌ {error}</p>
      )}

      {searched && !loading && !error && (
        <div className="screen-results">
          <h3>篩選結果（{results.length} 筆）</h3>
          {results.length === 0 ? (
            <p className="no-data">沒有符合條件的股票</p>
          ) : (
            <table className="result-table">
              <thead>
                <tr>
                  <th>代號</th>
                  <th>名稱</th>
                  <th>股價</th>
                  <th>週漲幅</th>
                  <th>成交量(張)</th>
                  <th>殖利率</th>
                  {hasMA && <th>{MA_OPTIONS.find(o => o.value === filters.near_ma)?.label}</th>}
                  {hasMA && <th>偏離</th>}
                  {hasPattern && <th>型態</th>}
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {results.map((s) => (
                  <tr key={s.ticker}>
                    <td>{s.ticker}</td>
                    <td>{s.name}</td>
                    <td>{s.price ?? "—"}</td>
                    <td className={s.weekly_change_pct > 0 ? "deviation-up" : s.weekly_change_pct < 0 ? "deviation-down" : ""}>
                      {s.weekly_change_pct != null ? `${s.weekly_change_pct > 0 ? "+" : ""}${s.weekly_change_pct}%` : "—"}
                    </td>
                    <td>{s.volume_zhang != null ? s.volume_zhang.toLocaleString() : "—"}</td>
                    <td>{s.dividend_yield ? `${s.dividend_yield}%` : "—"}</td>
                    {hasMA && <td>{s.ma_value ?? "—"}</td>}
                    {hasMA && (
                      <td className={
                        s.ma_deviation_pct > 0 ? "deviation-up"
                        : s.ma_deviation_pct < 0 ? "deviation-down"
                        : ""
                      }>
                        {s.ma_deviation_pct != null
                          ? `${s.ma_deviation_pct > 0 ? "+" : ""}${s.ma_deviation_pct}%`
                          : "—"}
                      </td>
                    )}
                    {hasPattern && (
                      <td className="pattern-tag">
                        {PATTERN_LABEL[s.pattern] ?? "—"}
                      </td>
                    )}
                    <td>
                      <button className="view-btn" onClick={() => onSelect(s.ticker)}>
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );

}
