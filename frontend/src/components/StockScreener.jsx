import { useState, useEffect } from "react";
import { screenStocks, scanWeeklySurge, scanMaSqueeze, scanNearEma60, scanVolumeBreakout, scanInstitutionalBuying, getEma60Watchlist, getEma60Breakouts } from "../api";
import { hasTodayCloseData } from "../marketHours";

// 後端不同掃描來源回傳的交易所欄位有的是原始代碼（TW/TWO），有的已經是中文，統一轉成手機版卡片用的縮寫
const EXCHANGE_TAG = { TW: "市", TWO: "櫃", "上市": "市", "上櫃": "櫃" };

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
  min_prev_day_change: "",
  ma20_rising: false,
  price_above_ma5_ma60: false,
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

export default function StockScreener({ onSelect, filters, setFilters, results, setResults, searched, setSearched, autoScan, onAutoScanHandled }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [resultMode, setResultMode] = useState(""); // "weekly_surge" | ""
  const [screenerTab, setScreenerTab] = useState("quick"); // "quick" | "condition"

  // 週漲幅急漲固定條件
  const WEEKLY_SURGE_PRESET = {
    min_weekly_change: "20",  // 週漲幅 ≥ 20%
    min_volume: "1000",       // 日成交量 ≥ 1000 張
    min_capital: "2",         // 股本 ≥ 2 億元
  };

  const handleWeeklySurge = async () => {
    setResultMode("weekly_surge");
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

  const handleNearEma60 = async () => {
    setResultMode("near_ema60");
    setLoading(true);
    setError(null);
    setResults([]);
    setFilters({ ...EMPTY_FILTERS });
    try {
      const res = await scanNearEma60(500);
      setResults(res.data.stocks);
      setSearched(true);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "掃描失敗");
      setSearched(true);
    } finally {
      setLoading(false);
    }
  };

  const handleEma60Watchlist = async () => {
    setResultMode("ema60_watchlist");
    setLoading(true);
    setError(null);
    setResults([]);
    setFilters({ ...EMPTY_FILTERS });
    try {
      const res = await getEma60Watchlist();
      setResults(res.data.stocks);
      setSearched(true);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "查詢失敗");
      setSearched(true);
    } finally {
      setLoading(false);
    }
  };

  const handleEma60Breakouts = async () => {
    setResultMode("ema60_breakout");
    setLoading(true);
    setError(null);
    setResults([]);
    setFilters({ ...EMPTY_FILTERS });
    try {
      const res = await getEma60Breakouts();
      setResults(res.data.stocks);
      setSearched(true);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "查詢失敗");
      setSearched(true);
    } finally {
      setLoading(false);
    }
  };

  const handleVolumeBreakout = async () => {
    setResultMode("volume_breakout");
    setLoading(true);
    setError(null);
    setResults([]);
    try {
      const res = await scanVolumeBreakout(200);
      setResults(res.data.stocks);
      setSearched(true);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "掃描失敗");
      setSearched(true);
    } finally {
      setLoading(false);
    }
  };

  const handleInstitutionalBuying = async () => {
    setResultMode("institutional_buying");
    setLoading(true);
    setError(null);
    setResults([]);
    try {
      const res = await scanInstitutionalBuying(3, 200, 2000);
      setResults(res.data.stocks);
      setSearched(true);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "掃描失敗");
      setSearched(true);
    } finally {
      setLoading(false);
    }
  };

  const handlePattern = async (pattern) => {
    const newFilters = { ...EMPTY_FILTERS, pattern, custom_tickers: filters.custom_tickers };
    setFilters(newFilters);
    // 鳥嘴與分歧：直接掃全市場 DB，不透過 screenStocks
    if (pattern === "bird_beak" && !newFilters.custom_tickers) {
      setResultMode("bird_beak");
      setLoading(true);
      setError(null);
      setResults([]);
      try {
        const res = await scanMaSqueeze(200);
        setResults(res.data.stocks);
        setSearched(true);
      } catch (e) {
        setError(e?.response?.data?.detail || e.message || "掃描失敗");
        setSearched(true);
      } finally {
        setLoading(false);
      }
      return;
    }
    setResultMode("");
    runScreen(newFilters);
  };

  // 從大盤狀態首頁「昨日/今日訊號」點進來時，帶著要跑哪個掃描一起過來，
  // 不然只是導到這一頁、畫面卻是空的，還要使用者自己再點一次按鈕。
  useEffect(() => {
    if (!autoScan) return;
    const runners = {
      near_ema60:            handleNearEma60,
      volume_breakout:       handleVolumeBreakout,
      institutional_buying:  handleInstitutionalBuying,
      ma_squeeze:            () => handlePattern("bird_beak"),
    };
    runners[autoScan]?.();
    onAutoScanHandled?.();
  }, [autoScan]);

  const handleScreen = () => runScreen(filters);

  const runScreen = async (f) => {
    setResultMode(""); // clear special modes
    setLoading(true);
    setError(null);
    setResults([]);
    try {
      const tickers = f.custom_tickers
        ? f.custom_tickers.split(/[,\s]+/).filter(Boolean)
        : [];

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
        min_prev_day_change: n(f.min_prev_day_change),
        ma20_rising: f.ma20_rising || false,
        price_above_ma5_ma60: f.price_above_ma5_ma60 || false,
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

  // 切分頁籤時把上一個分頁篩出來的結果清掉，不然切到「條件篩選」下面還會看到
  // 剛剛「快速篩選」跑出來的結果，容易誤會是條件篩選跑出來的。
  const switchTab = (tab) => {
    if (tab === screenerTab) return;
    setScreenerTab(tab);
    setResults([]);
    setSearched(false);
    setError(null);
    setResultMode("");
  };

  const hasMA = !!filters.near_ma;
  const hasPattern = !!filters.pattern;
  const isEma60Mode = resultMode === "near_ema60";
  const isEma60WatchlistMode = resultMode === "ema60_watchlist";
  const isEma60BreakoutMode = resultMode === "ema60_breakout";
  const isVolumeBreakoutMode = resultMode === "volume_breakout";
  const isInstitutionalBuyingMode = resultMode === "institutional_buying";
  const PATTERN_LABEL = { bird_beak: "⚡ 鳥嘴與分歧", divergence: "⚡ 鳥嘴與分歧" };

  return (
    <div className="page">
      <h2>選股篩選</h2>
      <p className="ranking-hint">
        全市場類的篩選（週漲幅急漲／鳥嘴與分歧／EMA60近線／貼線觀察名單／量價突破／法人連買）都是讀資料庫收盤價，
        平日 15:30 排程更新，目前顯示的是{hasTodayCloseData() ? "今天" : "前一個交易日"}收盤的資料，不是即時股價。
      </p>

      <div className="ranking-tabs">
        <button
          className={`ranking-tab ${screenerTab === "quick" ? "active" : ""}`}
          onClick={() => switchTab("quick")}
        >
          快速篩選
        </button>
        <button
          className={`ranking-tab ${screenerTab === "condition" ? "active" : ""}`}
          onClick={() => switchTab("condition")}
        >
          條件篩選
        </button>
      </div>

      {/* 快捷條件按鈕 */}
      {screenerTab === "quick" && (
      <div className="preset-bar">
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
          title="日K 5MA 與 20MA：近 15 天曾黏合後發散，MA5 站上 MA20 且收盤在 MA5 之上"
        >
          ⚡ 鳥嘴與分歧
          <span className="preset-btn-sub">日K 5MA／20MA</span>
        </button>
        <button
          className="preset-btn preset-btn--pattern"
          onClick={handleNearEma60}
          disabled={loading}
          title="收盤在 EMA60 上方 0~3%，近一個月持續站上 EMA60，日量 ≥ 2000 張"
        >
          📈 EMA60近線
        </button>
        <button
          className="preset-btn preset-btn--pattern"
          onClick={handleEma60Watchlist}
          disabled={loading}
          title="每天被 EMA60近線 掃到的股票會自動加進這份觀察名單，噴出（爆量或站回EMA10）就會發通知並移到「貼線噴出追蹤」；太久沒動靜也會自動清掉"
        >
          📋 貼線觀察名單
        </button>
        <button
          className="preset-btn preset-btn--pattern"
          onClick={handleEma60Breakouts}
          disabled={loading}
          title="最近30天內從貼線觀察名單噴出的股票，噴出後不會消失，繼續放這裡讓你追蹤後續表現（5/10/20個交易日報酬率會隨時間自動補上）"
        >
          🚀 貼線噴出追蹤
        </button>
        <button
          className="preset-btn preset-btn--pattern"
          onClick={handleVolumeBreakout}
          disabled={loading}
          title="今日成交量 ≥ 近5日均量3倍，且收盤價創近20日新高，日量 ≥ 2000 張"
        >
          💥 量價突破
        </button>
        <button
          className="preset-btn preset-btn--pattern"
          onClick={handleInstitutionalBuying}
          disabled={loading}
          title="外資＋投信合計買超連續 3 個交易日以上（不含自營商），合計買超 ≥ 2000 張"
        >
          🏦 法人連買
        </button>
      </div>
      )}

      {screenerTab === "condition" && (
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
                股價在均線上方 0~{filters.near_ma_pct}%
              </span>
            </div>
          </div>
        )}

        <div className="filter-row">
          <label>均線型態</label>
          <div className="pattern-btns">
            {[
              { value: "",           label: "不篩選" },
              { value: "bird_beak",  label: "⚡ 鳥嘴與分歧", desc: "日K 5MA 與 20MA：近 15 天曾黏合後發散，MA5 站上 MA20 且收盤在 MA5 之上" },
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
        <div className="filter-section-title">價量技術條件</div>

        <div className="filter-row">
          <label>前日漲幅 ≥ (%)</label>
          <input
            type="number"
            placeholder="例：9"
            value={filters.min_prev_day_change}
            onChange={(e) => setFilters({ ...filters, min_prev_day_change: e.target.value })}
          />
        </div>

        <div className="filter-row">
          <label>技術訊號</label>
          <div className="tech-signal-checks">
            <label className="check-label">
              <input
                type="checkbox"
                checked={filters.ma20_rising}
                onChange={(e) => setFilters({ ...filters, ma20_rising: e.target.checked })}
              />
              MA20 向上（今日 &gt; 昨日）
            </label>
            <label className="check-label">
              <input
                type="checkbox"
                checked={filters.price_above_ma5_ma60}
                onChange={(e) => setFilters({ ...filters, price_above_ma5_ma60: e.target.checked })}
              />
              收盤價 &gt; MA5 且 MA60
            </label>
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
      )}

      {loading && (
        <p className="loading-hint">正在掃描中，請稍候...</p>
      )}

      {searched && !loading && error && (
        <p className="error">❌ {error}</p>
      )}

      {searched && !loading && !error && (
        <div className="screen-results sticky-name-table">
          <h3>篩選結果（{results.length} 筆）</h3>
          {results.length === 0 ? (
            <p className="no-data">沒有符合條件的股票</p>
          ) : (
            <div className="ranking-table-wrap">
            <table className="result-table">
              <thead>
                <tr>
                  <th className="col-ticker">代號</th>
                  <th className="col-name">名稱</th>
                  <th>股價</th>
                  <th>漲跌幅</th>
                  {resultMode === "weekly_surge" && <th>週漲幅</th>}
                  {!isEma60WatchlistMode && !isEma60BreakoutMode && <th>成交量(張)</th>}
                  {isEma60Mode && <th>EMA60</th>}
                  {isEma60Mode && <th>偏離</th>}
                  {isEma60WatchlistMode && <th>貼線日期</th>}
                  {isEma60WatchlistMode && <th>進場價</th>}
                  {isEma60WatchlistMode && <th>累計漲幅</th>}
                  {isEma60BreakoutMode && <th>觸發日期</th>}
                  {isEma60BreakoutMode && <th>觸發價</th>}
                  {isEma60BreakoutMode && <th>累計漲幅</th>}
                  {isEma60BreakoutMode && <th>5日報酬</th>}
                  {isEma60BreakoutMode && <th>10日報酬</th>}
                  {isEma60BreakoutMode && <th>20日報酬</th>}
                  {isVolumeBreakoutMode && <th>量比</th>}
                  {isInstitutionalBuyingMode && <th>連續買超天數</th>}
                  {isInstitutionalBuyingMode && <th>合計買超(張)</th>}
                  {hasMA && <th>{MA_OPTIONS.find(o => o.value === filters.near_ma)?.label}</th>}
                  {hasMA && <th>偏離</th>}
                  {hasPattern && <th>型態</th>}
                </tr>
              </thead>
              <tbody>
                {results.map((s) => (
                  <tr
                    key={s.ticker}
                    className={`industry-row-clickable ${(() => { const v = s.change_pct ?? s.weekly_change_pct; return v > 0 ? "row-up" : v < 0 ? "row-down" : ""; })()}`}
                    onClick={() => onSelect(s.ticker, resultMode)}
                  >
                    <td className="col-ticker">{s.ticker}</td>
                    <td className="col-name">
                      <span className="col-name-full">{s.name}</span>
                      <span className="col-name-short">
                        {s.name && s.name.length > 4 ? `${s.name.slice(0, 4)}...` : s.name}
                      </span>
                      <span className="col-name-sub">
                        {s.exchange && (
                          <span className="mrc-exchange-tag">
                            {EXCHANGE_TAG[s.exchange] ?? s.exchange}
                          </span>
                        )}
                        <span className="mrc-ticker">{s.ticker}</span>
                      </span>
                    </td>
                    <td>{s.close ?? s.price ?? "—"}</td>
                    <td className={s.change_pct > 0 ? "deviation-up" : s.change_pct < 0 ? "deviation-down" : ""}>
                      {s.change_pct != null ? `${s.change_pct > 0 ? "+" : ""}${s.change_pct}%` : "—"}
                    </td>
                    {resultMode === "weekly_surge" && (
                      <td className={s.weekly_change_pct > 0 ? "deviation-up" : s.weekly_change_pct < 0 ? "deviation-down" : ""}>
                        {s.weekly_change_pct != null ? `${s.weekly_change_pct > 0 ? "+" : ""}${s.weekly_change_pct}%` : "—"}
                      </td>
                    )}
                    {!isEma60WatchlistMode && !isEma60BreakoutMode && (
                      <td>{s.volume_zhang != null ? s.volume_zhang.toLocaleString() : "—"}</td>
                    )}
                    {isEma60Mode && <td>{s.ema60 ?? "—"}</td>}
                    {isEma60Mode && (
                      <td className="deviation-up">
                        {s.dev_pct != null ? `+${s.dev_pct}%` : "—"}
                      </td>
                    )}
                    {isEma60WatchlistMode && <td>{s.first_seen_date ?? "—"}</td>}
                    {isEma60WatchlistMode && <td>{s.entry_price ?? "—"}</td>}
                    {isEma60WatchlistMode && (
                      <td className={s.since_entry_pct > 0 ? "deviation-up" : s.since_entry_pct < 0 ? "deviation-down" : ""}>
                        {s.since_entry_pct != null ? `${s.since_entry_pct > 0 ? "+" : ""}${s.since_entry_pct}%` : "—"}
                      </td>
                    )}
                    {isEma60BreakoutMode && <td>{s.trigger_date ?? "—"}</td>}
                    {isEma60BreakoutMode && <td>{s.trigger_price ?? "—"}</td>}
                    {isEma60BreakoutMode && (
                      <td className={s.since_trigger_pct > 0 ? "deviation-up" : s.since_trigger_pct < 0 ? "deviation-down" : ""}>
                        {s.since_trigger_pct != null ? `${s.since_trigger_pct > 0 ? "+" : ""}${s.since_trigger_pct}%` : "—"}
                      </td>
                    )}
                    {isEma60BreakoutMode && (
                      <td className={s.return_5d > 0 ? "deviation-up" : s.return_5d < 0 ? "deviation-down" : ""}>
                        {s.return_5d != null ? `${s.return_5d > 0 ? "+" : ""}${s.return_5d}%` : "—"}
                      </td>
                    )}
                    {isEma60BreakoutMode && (
                      <td className={s.return_10d > 0 ? "deviation-up" : s.return_10d < 0 ? "deviation-down" : ""}>
                        {s.return_10d != null ? `${s.return_10d > 0 ? "+" : ""}${s.return_10d}%` : "—"}
                      </td>
                    )}
                    {isEma60BreakoutMode && (
                      <td className={s.return_20d > 0 ? "deviation-up" : s.return_20d < 0 ? "deviation-down" : ""}>
                        {s.return_20d != null ? `${s.return_20d > 0 ? "+" : ""}${s.return_20d}%` : "—"}
                      </td>
                    )}
                    {isVolumeBreakoutMode && (
                      <td className="deviation-up">{s.vol_ratio != null ? `${s.vol_ratio}x` : "—"}</td>
                    )}
                    {isInstitutionalBuyingMode && <td>{s.streak_days ?? "—"}</td>}
                    {isInstitutionalBuyingMode && (
                      <td className="deviation-up">
                        {s.total_net_zhang != null ? s.total_net_zhang.toLocaleString() : "—"}
                      </td>
                    )}
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
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>
      )}
    </div>
  );

}
