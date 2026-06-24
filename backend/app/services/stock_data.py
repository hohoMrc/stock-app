import time
import requests
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# 簡易 TTL cache：key → (timestamp, value)
_info_cache: dict = {}
_history_cache: dict = {}
INFO_TTL = 300      # 個股基本資訊快取 5 分鐘
HISTORY_TTL = 600   # K 線資料快取 10 分鐘

def _cache_get(store: dict, key, ttl: int):
    entry = store.get(key)
    if entry and time.time() - entry[0] < ttl:
        return entry[1]
    return None

def _cache_set(store: dict, key, value):
    store[key] = (time.time(), value)

# 從證交所快取中文股名與產業別
_tw_stock_names: dict = {}
_tw_stock_industry: dict = {}  # ticker → 中文產業別
_tw_stock_exchange: dict = {}  # ticker → "TW" 或 "TWO"

# TWSE 產業別代碼對照
TWSE_INDUSTRY_CODE_MAP = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業",
    "04": "紡織纖維", "05": "電機機械", "06": "電器電纜",
    "08": "玻璃陶瓷", "09": "造紙工業", "10": "鋼鐵工業",
    "11": "橡膠工業", "12": "汽車工業", "14": "建材營造",
    "15": "航運業",   "16": "觀光餐旅", "17": "金融保險",
    "18": "貿易百貨", "20": "其他",     "21": "化學工業",
    "22": "生技醫療", "23": "油電燃氣", "24": "半導體業",
    "25": "電腦及週邊設備", "26": "光電業", "27": "通信網路",
    "28": "電子零組件", "29": "電子通路", "30": "資訊服務",
    "31": "其他電子", "32": "文化創意", "33": "農業科技",
    "34": "電子商務", "35": "綠能環保",
}

# 常見 ETF 中文名稱（TWSE 股票清單不含 ETF）
ETF_NAMES = {
    "0050": "元大台灣50",
    "0056": "元大高股息",
    "00878": "國泰永續高股息",
    "006208": "富邦台50",
    "00881": "國泰台灣5G+",
    "00885": "富邦越南",
    "00692": "富邦公司治理",
    "0052": "富邦科技",
    "0053": "元大電子",
    "00690": "兆豐藍籌30",
    "00713": "元大台灣高息低波",
    "00757": "統一FANG+",
    "00850": "元大臺灣ESG永續",
    "00900": "富邦特選高股息30",
}

# 針對 TWSE 分類太粗的個股，手動指定更細的產業
TICKER_INDUSTRY_OVERRIDE = {
    # 半導體細分
    "2330": "晶圓代工",   # 台積電
    "2303": "晶圓代工",   # 聯電
    "2344": "記憶體IC",   # 華邦電
    "2408": "DRAM記憶體", # 南科 (南亞科技)
    "4863": "記憶體模組", # 威剛
    "2454": "IC設計",     # 聯發科
    "2379": "IC設計",     # 瑞昱
    "3034": "IC設計",     # 聯詠
    "2358": "IC設計",     # 廷鑫
    "3711": "封裝測試",   # 日月光投控
    "2308": "電源管理",   # 台達電
    # 電子製造/組裝
    "2317": "電子代工(EMS)", # 鴻海
    "2354": "電子代工(EMS)", # 鴻準
    # 電腦週邊
    "2357": "筆電/主機板",  # 華碩
    "2353": "筆電",         # 宏碁
    # 光電
    "2382": "TFT-LCD面板",  # 廣達 (實際是筆電ODM)
    # 電信
    "2412": "電信服務",     # 中華電
    # 金融細分
    "2882": "壽險金控",  # 國泰金
    "2881": "壽險金控",  # 富邦金
    "2891": "銀行金控",  # 中信金
    "2886": "銀行金控",  # 兆豐金
    # 傳產
    "1301": "石化/塑膠",  # 台塑
    "1303": "石化/塑膠",  # 南亞
}

DEFAULT_TICKERS = [
    # 半導體
    "2330", "2303", "2454", "3711", "2379", "2344", "2408",
    # 電子製造 / 零組件
    "2317", "2357", "2308", "2382", "2395", "3008", "2301", "2327",
    # 通訊 / 網路
    "2412", "4904", "3045",
    # 金融
    "2882", "2881", "2891", "2886", "2884",
    # 石化 / 傳產
    "1301", "1303", "1326", "2002", "1101",
    # 股金寶找到的高週漲幅個股（供參考）
    "2481", "3588", "6168", "6226", "6243", "6573", "6834",
]


def _load_tw_stock_names():
    """從證交所與櫃買中心抓股票中文名稱與產業別"""
    global _tw_stock_names, _tw_stock_industry, _tw_stock_exchange
    if _tw_stock_names:
        return
    # 上市（TWSE）
    try:
        rows = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", timeout=10).json()
        for row in rows:
            code = row.get("公司代號", "").strip()
            name = row.get("公司簡稱", "").strip()
            industry_code = row.get("產業別", "").strip()
            if code and name:
                _tw_stock_names[code] = name
                _tw_stock_exchange[code] = "TW"
            if code and industry_code:
                _tw_stock_industry[code] = TWSE_INDUSTRY_CODE_MAP.get(industry_code, industry_code)
    except Exception:
        pass
    # 上櫃（TPEx）
    try:
        rows = requests.get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", timeout=10).json()
        for row in rows:
            code = row.get("SecuritiesCompanyCode", "").strip()
            name = row.get("CompanyAbbreviation", "").strip()
            industry_code = row.get("SecuritiesIndustryCode", "").strip()
            if code and name and code not in _tw_stock_names:
                _tw_stock_names[code] = name
                _tw_stock_exchange[code] = "TWO"
            if code and industry_code and code not in _tw_stock_industry:
                _tw_stock_industry[code] = TWSE_INDUSTRY_CODE_MAP.get(industry_code, industry_code)
    except Exception:
        pass


_TWSE_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _get_twse_realtime(ticker: str) -> dict:
    """從 TWSE/TPEx 即時行情 API 取得股價與成交量（不受 rate limit）"""
    _load_tw_stock_names()
    exchange = _tw_stock_exchange.get(ticker, "TW")
    prefix = "tse" if exchange == "TW" else "otc"
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={prefix}_{ticker}.tw&json=1&delay=0"
    try:
        resp = requests.get(url, timeout=10, headers=_TWSE_HEADERS)
        arr = resp.json().get("msgArray", [])
        if not arr:
            return {}
        item = arr[0]
        # z=即時價，非交易時間為"-"，改用 pz（前收盤）
        raw_price = item.get("z", "-")
        price = float(raw_price) if raw_price not in ("-", "", None) else None
        if price is None:
            pz = item.get("pz", "-")
            price = float(pz) if pz not in ("-", "", None) else None
        raw_vol = item.get("v", "-")
        volume_zhang = int(float(raw_vol)) if raw_vol not in ("-", "", None) else None
        return {
            "price": price,
            "volume_zhang": volume_zhang,
            "volume": volume_zhang * 1000 if volume_zhang else None,
        }
    except Exception:
        return {}


def get_stock_info(ticker: str) -> dict:
    """取得個股基本資訊：價格來自 TWSE 官方，PE/PB 來自 yfinance（允許失敗）"""
    cached = _cache_get(_info_cache, ticker, INFO_TTL)
    if cached:
        return cached

    _load_tw_stock_names()

    # 主要：TWSE/TPEx 即時行情（穩定，不受 rate limit）
    twse = _get_twse_realtime(ticker)
    price = twse.get("price")
    volume = twse.get("volume")
    volume_zhang = twse.get("volume_zhang")

    # 次要：yfinance 取 PE/PB/市值（允許失敗，失敗給 None）
    yf_info = {}
    try:
        exchange = _tw_stock_exchange.get(ticker, "TW")
        suffix = ".TW" if exchange == "TW" else ".TWO"
        symbol = f"{ticker}{suffix}"
        _symbol_cache[ticker] = symbol
        yf_info = yf.Ticker(symbol).fast_info  # fast_info 較輕量
    except Exception:
        pass

    # 名稱、產業
    is_etf = ticker in ETF_NAMES
    display_name = (ETF_NAMES.get(ticker) if is_etf else _tw_stock_names.get(ticker)) or ticker
    industry = (
        "ETF 指數股票型基金" if is_etf
        else TICKER_INDUSTRY_OVERRIDE.get(ticker)
        or _tw_stock_industry.get(ticker)
    )

    # fast_info 欄位名稱不同
    mktcap = getattr(yf_info, "market_cap", None)
    shares = getattr(yf_info, "shares", None)
    week_52_high = getattr(yf_info, "year_high", None)
    week_52_low  = getattr(yf_info, "year_low", None)

    # 市值：優先 yfinance，次選 TWSE 價格 × 股數
    if not mktcap and price and shares:
        mktcap = price * shares
    capital_yi = round(shares * 10 / 1e8, 1) if shares else None

    result = {
        "ticker": ticker,
        "name": display_name,
        "price": price,
        "pe_ratio": getattr(yf_info, "pe_forward", None),
        "pb_ratio": None,
        "dividend_yield": None,
        "market_cap": mktcap,
        "market_cap_yi": round(mktcap / 1e8, 1) if mktcap else None,
        "capital_yi": capital_yi,
        "volume": volume,
        "volume_zhang": volume_zhang,
        "week_52_high": week_52_high,
        "week_52_low": week_52_low,
        "sector": None,
        "industry": industry,
    }
    _cache_set(_info_cache, ticker, result)
    return result


def get_stocks_by_industry(industry_zh: str, exclude_ticker: str = None) -> list:
    """找出相同產業的其他股票（從預設清單搜尋）"""
    results = []
    for ticker in DEFAULT_TICKERS:
        if ticker == exclude_ticker:
            continue
        try:
            info = get_stock_info(ticker)
            if info.get("industry") == industry_zh and info.get("price"):
                results.append(info)
        except Exception:
            continue
    return results


MA_PERIODS = {
    "ma5":  {"days": 5,   "label": "週線(MA5)"},
    "ma20": {"days": 20,  "label": "月線(MA20)"},
    "ma60": {"days": 60,  "label": "季線(MA60)"},
    "ma240":{"days": 240, "label": "年線(MA240)"},
}


_symbol_cache: dict = {}

def _get_symbol(ticker: str) -> str:
    """判斷股票是上市(.TW)還是上櫃(.TWO)，結果快取避免重複查"""
    if ticker in _symbol_cache:
        return _symbol_cache[ticker]
    for suffix in [".TW", ".TWO"]:
        hist = yf.Ticker(f"{ticker}{suffix}").history(period="5d")
        if not hist.empty:
            _symbol_cache[ticker] = f"{ticker}{suffix}"
            return _symbol_cache[ticker]
    _symbol_cache[ticker] = f"{ticker}.TW"
    return _symbol_cache[ticker]


_PERIOD_MONTHS = {
    "1mo": 1, "3mo": 3, "6mo": 6, "1y": 12, "2y": 24, "5y": 60,
}


def _fetch_twse_month(ticker: str, year: int, month: int, exchange: str) -> list:
    """抓單月 OHLC（上市用 TWSE，上櫃用 TPEx）"""
    date_str = f"{year}{month:02d}01"
    try:
        if exchange == "TW":
            url = (f"https://www.twse.com.tw/exchangeReport/STOCK_DAY"
                   f"?response=json&date={date_str}&stockNo={ticker}")
            resp = requests.get(url, timeout=10, headers=_TWSE_HEADERS)
            data = resp.json()
            if data.get("stat") != "OK":
                return []
            rows = data.get("data", [])
            result = []
            for row in rows:
                try:
                    # 日期格式：民國年/月/日 → 西元
                    parts = row[0].split("/")
                    w_year = int(parts[0]) + 1911
                    date = f"{w_year}-{parts[1]}-{parts[2]}"
                    result.append({
                        "date": date,
                        "open":   float(row[3].replace(",", "")),
                        "high":   float(row[4].replace(",", "")),
                        "low":    float(row[5].replace(",", "")),
                        "close":  float(row[6].replace(",", "")),
                        "volume": int(row[1].replace(",", "")),
                    })
                except (ValueError, IndexError):
                    continue
            return result
        else:  # TWO (上櫃)
            roc_year = year - 1911
            url = (f"https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/"
                   f"st43_result.php?l=zh-tw&d={roc_year}/{month:02d}&stkno={ticker}&s=0,asc,0")
            resp = requests.get(url, timeout=10, headers=_TWSE_HEADERS)
            data = resp.json()
            rows = data.get("aaData", [])
            result = []
            for row in rows:
                try:
                    parts = row[0].split("/")
                    w_year = int(parts[0]) + 1911
                    date = f"{w_year}-{parts[1]}-{parts[2]}"
                    result.append({
                        "date": date,
                        "open":   float(row[3].replace(",", "")),
                        "high":   float(row[4].replace(",", "")),
                        "low":    float(row[5].replace(",", "")),
                        "close":  float(row[6].replace(",", "")),
                        "volume": int(row[1].replace(",", "")),
                    })
                except (ValueError, IndexError):
                    continue
            return result
    except Exception:
        return []


def get_stock_history(ticker: str, period: str = "3mo", interval: str = "1d") -> list:
    """取得個股歷史股價（TWSE/TPEx 官方 API，不受 rate limit）"""
    cache_key = (ticker, period, interval)
    cached = _cache_get(_history_cache, cache_key, HISTORY_TTL)
    if cached is not None:
        return cached

    _load_tw_stock_names()
    exchange = _tw_stock_exchange.get(ticker, "TW")
    months_needed = _PERIOD_MONTHS.get(period, 3)

    today = pd.Timestamp.now()
    all_records = []
    for i in range(months_needed):
        target = today - pd.DateOffset(months=i)
        month_records = _fetch_twse_month(ticker, target.year, target.month, exchange)
        all_records.extend(month_records)
        if i < months_needed - 1:
            time.sleep(0.2)  # 避免對官方 API 請求過快

    all_records.sort(key=lambda x: x["date"])

    # 週K / 月K 重採樣
    if interval in ("1wk", "1mo") and all_records:
        df = pd.DataFrame(all_records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df.columns = ["Open", "High", "Low", "Close", "Volume"]
        rule = "W-FRI" if interval == "1wk" else "ME"
        df = df.resample(rule).agg(
            Open=("Open","first"), High=("High","max"),
            Low=("Low","min"), Close=("Close","last"),
            Volume=("Volume","sum")
        ).dropna(subset=["Open"])
        all_records = [
            {"date": d.strftime("%Y-%m-%d"), "open": round(r.Open,2),
             "high": round(r.High,2), "low": round(r.Low,2),
             "close": round(r.Close,2), "volume": int(r.Volume)}
            for d, r in df.iterrows()
        ]

    _cache_set(_history_cache, cache_key, all_records)
    return all_records


def _get_weekly_change(ticker: str):
    """計算週漲幅：本週收盤 vs 上週五收盤，與週K圖表顯示一致"""
    symbol = _get_symbol(ticker)
    hist = yf.Ticker(symbol).history(period="1mo")
    if hist.empty:
        return None
    # 重採樣為週K（以週五為結束日），取最後兩根收盤
    weekly = hist["Close"].resample("W-FRI").last().dropna()
    if len(weekly) < 2:
        return None
    prev_close = weekly.iloc[-2]
    curr_close = weekly.iloc[-1]
    return round((curr_close - prev_close) / prev_close * 100, 2)


def scan_all_weekly_surge(min_weekly_change: float = 20.0,
                          min_volume: float = None,
                          min_capital: float = None) -> list:
    """
    全市場批次掃描週漲幅。
    Step 1: yf.download 批次抓 1 個月收盤，計算週漲幅（批次快速）。
    Step 2: 符合週漲幅門檻的股票，並行抓詳細資訊做 volume/capital 篩選。
    """
    _load_tw_stock_names()

    # 只保留 4~5 位純數字代號（排除權證、ETF 等）
    def is_regular(code: str) -> bool:
        return code.isdigit() and 4 <= len(code) <= 5

    groups = {"TW": [], "TWO": []}
    for ticker, ex in _tw_stock_exchange.items():
        if is_regular(ticker):
            groups[ex].append(ticker)

    weekly_map: dict = {}
    BATCH = 200

    for suffix, tickers in [(".TW", groups["TW"]), (".TWO", groups["TWO"])]:
        for i in range(0, len(tickers), BATCH):
            batch = tickers[i:i + BATCH]
            syms = [f"{t}{suffix}" for t in batch]
            try:
                raw = yf.download(
                    syms, period="1mo",
                    group_by="ticker", auto_adjust=True,
                    progress=False, threads=True
                )
                if raw.empty:
                    continue
                single = len(syms) == 1
                for ticker, sym in zip(batch, syms):
                    try:
                        col = raw["Close"] if single else raw[sym]["Close"]
                        weekly = col.resample("W-FRI").last().dropna()
                        if len(weekly) < 2:
                            continue
                        chg = (weekly.iloc[-1] - weekly.iloc[-2]) / weekly.iloc[-2] * 100
                        if chg >= min_weekly_change:
                            weekly_map[ticker] = round(float(chg), 2)
                            _symbol_cache[ticker] = sym
                    except Exception:
                        pass
            except Exception:
                pass

    # Step 2：並行抓個股詳細資訊
    filters = {}
    if min_volume:
        filters["min_volume"] = min_volume
    if min_capital:
        filters["min_capital"] = min_capital

    candidates = sorted(weekly_map.items(), key=lambda x: -x[1])

    def fetch_info(ticker_wchg):
        ticker, wchg = ticker_wchg
        try:
            info = get_stock_info(ticker)
            if not info.get("price"):
                return None
            info["weekly_change_pct"] = wchg
            if filters and not _passes_basic_filters(info, filters):
                return None
            return info
        except Exception:
            return None

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_info, c): c for c in candidates}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)

    return sorted(results, key=lambda x: x.get("weekly_change_pct", 0), reverse=True)


def _calc_ma(ticker: str, ma_key: str):
    """計算指定均線，回傳 (目前股價, MA值, 偏離%) 或 None"""
    days = MA_PERIODS[ma_key]["days"]
    needed_period = "1y" if days <= 60 else "2y"
    symbol = _get_symbol(ticker)
    hist = yf.Ticker(symbol).history(period=needed_period)

    if hist.empty or len(hist) < days:
        return None

    closes = hist["Close"].values
    ma_value = round(float(closes[-days:].mean()), 2)
    current_price = round(float(closes[-1]), 2)
    deviation_pct = round((current_price - ma_value) / ma_value * 100, 2)

    return {"price": current_price, "ma": ma_value, "deviation_pct": deviation_pct}


def _detect_ma_pattern(ticker: str) -> dict:
    """
    偵測鳥嘴與分歧型態。
    - 鳥嘴：MA5 從下方逼近 MA20，gap 縮小中，MA5 上升
    - 分歧：MA5 在 MA20 上方，兩線曾幾乎重疊但未死亡交叉，現在再度分開
    """
    symbol = _get_symbol(ticker)
    hist = yf.Ticker(symbol).history(period="3mo")

    if hist.empty or len(hist) < 25:
        return {"bird_beak": False, "divergence": False}

    closes = pd.Series(hist["Close"].values)
    ma5_all  = closes.rolling(5).mean().dropna().values
    ma20_all = closes.rolling(20).mean().dropna().values

    # ma5_all[0] 對應 day4，ma20_all[0] 對應 day19
    # 對齊：ma5_all[15:] 與 ma20_all[:] 為同一天
    if len(ma5_all) < 16 or len(ma20_all) < 10:
        return {"bird_beak": False, "divergence": False}

    ma5  = ma5_all[15:]
    ma20 = ma20_all
    n = min(len(ma5), len(ma20))
    ma5, ma20 = ma5[-n:], ma20[-n:]

    # gap 比例（正 = MA5 在 MA20 上方）
    gaps = (ma5 - ma20) / ma20
    cur  = gaps[-1]

    # 鳥嘴用 10 天窗口；分歧用較短的 6 天確保訊號新鮮
    WINDOW_BIRD = 10
    WINDOW_DIV  = 6
    recent_bird = gaps[-WINDOW_BIRD:]
    recent_div  = gaps[-WINDOW_DIV:]

    # ── 鳥嘴 ──────────────────────────────────────────────
    # gap 在 -4% ~ +1%（MA5 逼近或剛越過 MA20）
    # 近 10 天 gap 持續縮小，MA5 上升
    bird_beak = False
    if -0.04 <= cur <= 0.01:
        gap_shrinking = recent_bird[-1] > recent_bird[0]
        ma5_rising    = ma5[-1] > ma5[-5] if len(ma5) >= 5 else False
        bird_beak     = gap_shrinking and ma5_rising

    # ── 分歧 ──────────────────────────────────────────────
    # 近 6 天內 MA5/MA20 曾幾乎黏合（gap < 2%），現在 MA5 已上方且 gap < 10%
    # MA5 不能跌破 MA20 超過 0.5%（否則是死叉 → 應歸類為鳥嘴）
    divergence = False
    if 0.005 < cur < 0.10:
        abs_recent = [abs(g) for g in recent_div]
        min_gap    = min(abs_recent)
        min_idx    = abs_recent.index(min_gap)
        min_actual = recent_div[min_idx]
        if (min_gap < 0.02
                and 0 < min_idx < WINDOW_DIV - 2
                and min_actual >= -0.005           # 允許極短暫觸碰但不能真的死叉
                and all(g >= -0.005 for g in recent_div)
                and cur - min_actual > 0.005):
            divergence = True

    return {"bird_beak": bird_beak, "divergence": divergence}


def screen_stocks(tickers: list, filters: dict) -> list:
    """根據條件篩選股票"""
    near_ma         = filters.get("near_ma")
    near_ma_pct     = filters.get("near_ma_pct", 3.0)
    pattern         = filters.get("pattern")
    min_weekly_chg  = filters.get("min_weekly_change")

    results = []
    for ticker in tickers:
        try:
            info = get_stock_info(ticker)
            if not _passes_basic_filters(info, filters):
                continue

            # 週漲幅篩選（需額外抓 10d 歷史，但比均線快）
            if min_weekly_chg is not None:
                wchg = _get_weekly_change(ticker)
                if wchg is None or wchg < min_weekly_chg:
                    continue
                info["weekly_change_pct"] = wchg

            # 均線位置篩選
            if near_ma and near_ma in MA_PERIODS:
                ma_data = _calc_ma(ticker, near_ma)
                if ma_data is None:
                    continue
                if abs(ma_data["deviation_pct"]) > near_ma_pct:
                    continue
                info["ma_value"] = ma_data["ma"]
                info["ma_deviation_pct"] = ma_data["deviation_pct"]
                info["ma_label"] = MA_PERIODS[near_ma]["label"]

            # 型態篩選
            if pattern in ("bird_beak", "divergence"):
                detected = _detect_ma_pattern(ticker)
                if not detected.get(pattern):
                    continue
                info["pattern"] = pattern

            results.append(info)
        except Exception:
            continue
    return results


def _passes_basic_filters(info: dict, filters: dict) -> bool:
    price   = info.get("price")
    volume  = info.get("volume_zhang")   # 張
    mktcap  = info.get("market_cap_yi")  # 億元
    capital = info.get("capital_yi")     # 股本億元
    pe      = info.get("pe_ratio")
    div     = info.get("dividend_yield")

    # 股價範圍
    if filters.get("min_price") and price and price < filters["min_price"]:
        return False
    if filters.get("max_price") and price and price > filters["max_price"]:
        return False
    # 日成交量（張）
    if filters.get("min_volume") and volume and volume < filters["min_volume"]:
        return False
    # 市值（億元）
    if filters.get("min_market_cap") and mktcap and mktcap < filters["min_market_cap"]:
        return False
    if filters.get("max_market_cap") and mktcap and mktcap > filters["max_market_cap"]:
        return False
    # 股本（億元）
    if filters.get("min_capital") and capital and capital < filters["min_capital"]:
        return False
    # 本益比
    if filters.get("max_pe") and pe and pe > filters["max_pe"]:
        return False
    if filters.get("min_pe") and pe and pe < filters["min_pe"]:
        return False
    # 殖利率
    if filters.get("min_dividend_yield") and div and div < filters["min_dividend_yield"]:
        return False

    return True
