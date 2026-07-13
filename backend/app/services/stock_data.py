import os
import base64
import tempfile
import threading
import time
import requests
import yfinance as yf
import pandas as pd
from datetime import date, timedelta, datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.db import get_candles, save_candles, is_candles_fresh, get_stock_meta, save_stock_meta

# ── Fugle / Fubon 行情客戶端（懶初始化）─────────────────────────────────────
_fugle_client = None
_fugle_sdk    = None
_fugle_available = None  # None=尚未嘗試, True=可用, False=不可用
_fugle_lock   = threading.Lock()

_PERIOD_DAYS = {"5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}


def _init_fugle():
    """用 Fubon API Key 登入，取得 Fugle 行情 token 並建立 RestClient。"""
    global _fugle_client, _fugle_sdk, _fugle_available
    pid      = os.environ.get("FUBON_PERSONAL_ID")
    api_key  = os.environ.get("FUBON_API_KEY")
    cert_b64 = os.environ.get("FUBON_CERT_B64")
    cert_pw  = os.environ.get("FUBON_CERT_PASS")

    if not all([pid, api_key, cert_b64, cert_pw]):
        print("[Fubon] 環境變數未設定，略過 Fugle 初始化")
        _fugle_available = False
        return

    try:
        from fubon_neo.sdk import FubonSDK

        cert_data = base64.b64decode(cert_b64)
        fd, cert_path = tempfile.mkstemp(suffix=".p12")
        try:
            os.write(fd, cert_data)
            os.close(fd)
            sdk = FubonSDK()
            result = sdk.apikey_login(pid, api_key, cert_path, cert_pw)
        finally:
            try:
                os.unlink(cert_path)
            except Exception:
                pass

        if not result.is_success:
            print(f"[Fubon] 登入失敗: {result.message}")
            _fugle_available = False
            return

        sdk.init_realtime()          # 建立 marketdata.rest_client（用 sdk_token 認證）
        _fugle_client = sdk.marketdata.rest_client
        _fugle_sdk    = sdk
        _fugle_available = True
        print("[Fubon] Fugle 行情客戶端初始化成功")

    except ImportError as e:
        print(f"[Fubon] 套件未安裝，略過: {e}")
        _fugle_available = False
    except Exception as e:
        print(f"[Fubon] 初始化失敗: {e}")
        _fugle_available = False


def _get_fugle():
    """取得 Fugle RestClient，首次呼叫時做懶初始化。"""
    global _fugle_available
    if _fugle_available is None:
        with _fugle_lock:
            if _fugle_available is None:
                _init_fugle()
    return _fugle_client if _fugle_available else None


def _fugle_quote(ticker: str) -> dict:
    """從 Fugle intraday quote 取得即時報價。"""
    client = _get_fugle()
    if not client:
        return {}
    try:
        resp = client.stock.intraday.quote(symbol=ticker)
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        if not isinstance(data, dict):
            data = {}
        price  = data.get("closePrice") or data.get("lastPrice") or data.get("referencePrice")
        total  = data.get("total") or {}
        # total.tradeVolume 單位為張，×1000 轉股數
        vol_zhang = total.get("tradeVolume")
        volume_int = int(vol_zhang) * 1000 if vol_zhang is not None else None
        name   = data.get("name")
        chg    = data.get("change")
        chg_pct = data.get("changePercent")
        # volume 可能為 0（收盤後重置），用 is not None 判斷
        return {
            "price":        round(float(price), 2) if price else None,
            "volume":       volume_int,
            "volume_zhang": int(vol_zhang) if vol_zhang is not None else None,
            "name":         name,
            "exchange":     data.get("exchange"),
            "change":       round(float(chg), 2) if chg is not None else None,
            "change_pct":   round(float(chg_pct), 2) if chg_pct is not None else None,
            # 今日 OHLC（供補今日 K 棒用）
            "open":   round(float(data["openPrice"]),  2) if data.get("openPrice")  else None,
            "high":   round(float(data["highPrice"]),  2) if data.get("highPrice")  else None,
            "low":    round(float(data["lowPrice"]),   2) if data.get("lowPrice")   else None,
            # Fugle quote 所屬日期（非交易日時會是最後一個交易日，用來排除假日補棒）
            "quote_date": data.get("date"),
        }
    except Exception as e:
        print(f"[Fugle] quote {ticker} 失敗: {e}")
        return {}


def _fugle_ticker(ticker: str) -> dict:
    """從 Fugle intraday ticker 取得股票基本資訊（股名、市場別、產業別、注意/處置股）。"""
    client = _get_fugle()
    if not client:
        return {}
    try:
        resp = client.stock.intraday.ticker(symbol=ticker)
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        if not isinstance(data, dict):
            data = {}
        return {
            "name":                    data.get("name"),
            "exchange":                data.get("exchange"),
            "market":                  data.get("market"),
            "industry":                data.get("industry"),
            "is_attention":            bool(data.get("isAttention",            False)),
            "is_disposition":          bool(data.get("isDisposition",          False)),
            "is_halted":               bool(data.get("isHalted",               False)),
            "is_unusually_recommended":bool(data.get("isUnusuallyRecommended", False)),
            "is_specific_abnormally":  bool(data.get("isSpecificAbnormally",   False)),
        }
    except Exception as e:
        print(f"[Fugle] ticker {ticker} 失敗: {e}")
        return {}


def _fugle_candles(ticker: str, from_date: str, to_date: str) -> list:
    """從 Fugle historical candles 取得日K，回傳 list of {date,open,high,low,close,volume(股數)}。"""
    client = _get_fugle()
    if not client:
        return []
    try:
        resp = client.stock.historical.candles(**{
            "symbol": ticker,
            "from":   from_date,
            "to":     to_date,
            "fields": "open,high,low,close,volume",
        })
        raw     = resp.get("data", []) if isinstance(resp, dict) else []
        candles = raw if isinstance(raw, list) else raw.get("candles", [])
        result  = []
        for c in candles:
            if not c.get("close"):
                continue
            d = str(c["date"])[:10]
            # Fugle 偶爾會把當日盤中資料誤標到隔壁的非交易日（例：週一資料標成週日），
            # 台股週六日絕不開盤，直接濾掉避免圖表出現假 K 棒
            try:
                if datetime.strptime(d, "%Y-%m-%d").weekday() >= 5:
                    continue
            except ValueError:
                continue
            vol_shares = c.get("volume", 0) or 0   # Fugle 歷史 K 線 volume 實際單位為股數
            result.append({
                "date":   d,
                "open":   round(float(c.get("open",  c["close"])), 2),
                "high":   round(float(c.get("high",  c["close"])), 2),
                "low":    round(float(c.get("low",   c["close"])), 2),
                "close":  round(float(c["close"]), 2),
                "volume": int(vol_shares),  # 已是股數，直接使用
            })
        return sorted(result, key=lambda x: x["date"])
    except Exception as e:
        print(f"[Fugle] candles {ticker} 失敗: {e}")
        return []


# ── TTL cache ──────────────────────────────────────────────────────────────────
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
_tw_stock_industry: dict = {}   # ticker → 中文產業別
_tw_stock_exchange: dict = {}   # ticker → "TW" 或 "TWO"
_tw_stock_capital: dict = {}    # ticker → 實收資本額（千元）
_tw_stock_names_attempted = False  # 避免每次請求都重試失敗的 TWSE 連線

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

# 常見台股名稱（TWSE 被封時的靜態備援，供股名搜尋使用）
COMMON_STOCK_NAMES: dict[str, str] = {
    # 半導體
    "2330": "台積電", "2303": "聯電", "2454": "聯發科", "3711": "日月光投控",
    "2379": "瑞昱", "2344": "華邦電", "2408": "南亞科技", "3034": "聯詠",
    "3008": "大立光", "6415": "矽力-KY", "5347": "世界先進", "2449": "京元電子",
    "2337": "旺宏", "2388": "威盛", "3443": "創意", "6770": "力積電",
    # 電子製造 / 零組件
    "2317": "鴻海", "2357": "華碩", "2308": "台達電", "2382": "廣達",
    "2395": "研華", "2301": "光寶科", "2327": "國巨", "2353": "宏碁",
    "2354": "鴻準", "2360": "致茂", "2352": "佳世達", "3231": "緯創",
    "2356": "英業達", "3673": "TPK宸鴻", "6669": "緯穎",
    # 電信
    "2412": "中華電", "4904": "遠傳", "3045": "台灣大",
    # 金融
    "2882": "國泰金", "2881": "富邦金", "2891": "中信金", "2886": "兆豐金",
    "2884": "玉山金", "2885": "元大金", "2892": "第一金", "2880": "華南金",
    "5880": "合庫金", "2883": "開發金", "2887": "台新金", "2890": "永豐金",
    "5876": "上海商銀", "2889": "國票金", "2888": "新光金",
    # 石化 / 傳產
    "1301": "台塑", "1303": "南亞", "1326": "台化", "2002": "中鋼",
    "1101": "台泥", "1216": "統一", "1402": "遠東新", "9910": "豐泰",
    # 汽車 / 零售
    "2207": "和泰車", "2912": "統一超", "2903": "遠百", "5903": "全家",
    # 生技 / 醫療
    "4711": "中裕", "6547": "晟德", "1707": "葡萄王", "4720": "友華",
    # 其他科技
    "2481": "強茂", "3588": "通嘉", "6168": "宏齊", "6226": "光隆精密",
    "6243": "迅杰", "6573": "虹揚-KY", "6834": "普鴻",
    "5464": "霖宏", "5425": "台半", "6271": "同欣電", "3665": "貿聯-KY",
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
    """從證交所與櫃買中心抓股票中文名稱、產業別、實收資本額（每次程序生命週期只嘗試一次）"""
    global _tw_stock_names, _tw_stock_industry, _tw_stock_exchange, _tw_stock_capital, _tw_stock_names_attempted
    if _tw_stock_names or _tw_stock_names_attempted:
        return
    _tw_stock_names_attempted = True
    # 上市（TWSE）
    try:
        rows = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", timeout=10).json()
        if rows:
            print(f"[TWSE] t187ap03_L sample keys: {list(rows[0].keys())}")
        for row in rows:
            code = row.get("公司代號", "").strip()
            name = row.get("公司簡稱", "").strip()
            industry_code = row.get("產業別", "").strip()
            capital_str = row.get("實收資本額", "").replace(",", "").strip()
            if code and name:
                _tw_stock_names[code] = name
                _tw_stock_exchange[code] = "TW"
            if code and industry_code:
                _tw_stock_industry[code] = TWSE_INDUSTRY_CODE_MAP.get(industry_code, industry_code)
            if code and capital_str:
                try:
                    _tw_stock_capital[code] = float(capital_str)
                except ValueError:
                    pass
        print(f"[TWSE] 上市股票清單載入 {len(_tw_stock_names)} 筆，資本額 {len(_tw_stock_capital)} 筆")
    except Exception as e:
        print(f"[TWSE] 上市股票清單載入失敗: {e}")
    # 上櫃（TPEx）
    try:
        rows = requests.get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", timeout=10).json()
        if rows:
            print(f"[TPEx] t187ap03_O sample keys: {list(rows[0].keys())}")
        for row in rows:
            code = row.get("SecuritiesCompanyCode", "").strip()
            name = row.get("CompanyAbbreviation", "").strip()
            industry_code = row.get("SecuritiesIndustryCode", "").strip()
            # TPEx 資本額欄位嘗試多個可能名稱
            capital_raw = (row.get("PaidInCapitalNTD") or row.get("實收資本額") or row.get("Capital") or "")
            capital_str = str(capital_raw).replace(",", "").strip()
            if code and name and code not in _tw_stock_names:
                _tw_stock_names[code] = name
                _tw_stock_exchange[code] = "TWO"
            if code and industry_code and code not in _tw_stock_industry:
                _tw_stock_industry[code] = TWSE_INDUSTRY_CODE_MAP.get(industry_code, industry_code)
            if code and capital_str and code not in _tw_stock_capital:
                try:
                    _tw_stock_capital[code] = float(capital_str)
                except ValueError:
                    pass
    except Exception:
        pass


_TWSE_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _fetch_twse_price(ticker: str, prefix: str) -> dict:
    """用指定前綴（tse/otc）查 TWSE 即時行情，回傳 {price, volume_zhang, volume}"""
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={prefix}_{ticker}.tw&json=1&delay=0"
    try:
        resp = requests.get(url, timeout=10, headers=_TWSE_HEADERS)
        arr = resp.json().get("msgArray", [])
        if not arr:
            return {}
        item = arr[0]
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


def _get_twse_realtime(ticker: str) -> dict:
    """從 TWSE/TPEx 即時行情 API 取得股價。
    若 TWSE 清單未載入（美國機房常見），自動嘗試 tse/otc 兩種前綴。
    """
    _load_tw_stock_names()
    exchange = _tw_stock_exchange.get(ticker)  # None 表示清單未載入
    if exchange:
        # 已知交易所，直接查
        prefix = "tse" if exchange == "TW" else "otc"
        return _fetch_twse_price(ticker, prefix)
    else:
        # 未知交易所（清單載入失敗），tse 先試，失敗再試 otc
        result = _fetch_twse_price(ticker, "tse")
        if result.get("price"):
            _tw_stock_exchange[ticker] = "TW"
            return result
        result = _fetch_twse_price(ticker, "otc")
        if result.get("price"):
            _tw_stock_exchange[ticker] = "TWO"
        return result


def get_stock_info(ticker: str) -> dict:
    """取得個股基本資訊。
    價格/成交量：優先 Fugle → TWSE 即時 API → yfinance chart API
    PE/市值：yfinance fast_info（失敗給 None）
    """
    cached = _cache_get(_info_cache, ticker, INFO_TTL)
    if cached:
        return cached

    _load_tw_stock_names()

    # 1a) Fugle ticker — 股票基本資訊（股名、產業別、注意/處置股）
    fugle_t = _fugle_ticker(ticker)

    # 1b) Fugle 即時報價（價格、成交量）
    fugle_q = _fugle_quote(ticker)

    # 用 Fugle 回傳的交易所更新本地映射（比 TWSE 清單更即時）
    fugle_exchange_raw = fugle_t.get("exchange") or fugle_q.get("exchange")
    if fugle_exchange_raw == "TWSE":
        _tw_stock_exchange[ticker] = "TW"
    elif fugle_exchange_raw in ("TPEX", "TPEx"):
        _tw_stock_exchange[ticker] = "TWO"

    exchange = _tw_stock_exchange.get(ticker, "TW")
    suffix   = ".TW" if exchange == "TW" else ".TWO"
    symbol   = f"{ticker}{suffix}"
    _symbol_cache[ticker] = symbol

    price        = None
    volume       = None
    volume_zhang = None
    week_52_high = None
    week_52_low  = None
    price_source = None

    if fugle_q.get("price"):
        price        = fugle_q["price"]
        volume       = fugle_q.get("volume")
        volume_zhang = fugle_q.get("volume_zhang")
        price_source = "fugle"

    # 2) TWSE/TPEx 官方即時 API
    if not price:
        twse = _get_twse_realtime(ticker)
        price        = twse.get("price")
        volume       = twse.get("volume")
        volume_zhang = twse.get("volume_zhang")
        if price:
            price_source = "twse"

    # 3) yfinance chart API（最後手段）
    if not price:
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if not hist.empty:
                price        = round(float(hist["Close"].iloc[-1]), 2)
                volume       = int(hist["Volume"].iloc[-1])
                volume_zhang = round(volume / 1000)
                week_52_high = round(float(hist["High"].max()), 2)
                week_52_low  = round(float(hist["Low"].min()), 2)
                price_source = "yfinance"
        except Exception:
            pass

    # 4) 成交量備援：收盤後即時 API 不提供量，從 TWSE 月報取今日數字
    if price and not volume:
        try:
            today_d  = date.today()
            exch     = _tw_stock_exchange.get(ticker, "TW")
            monthly  = _fetch_twse_month(ticker, today_d.year, today_d.month, exch)
            if monthly and monthly[-1]["date"] == today_d.strftime("%Y-%m-%d"):
                volume       = monthly[-1]["volume"]
                volume_zhang = round(volume / 1000) if volume else None
        except Exception:
            pass

    # Fugle historical stats：52週高低
    dividend_yield = None
    fugle_client = _get_fugle()
    if fugle_client:
        try:
            stats_resp = fugle_client.stock.historical.stats(symbol=ticker)
            stats_data = stats_resp.get("data", stats_resp) if isinstance(stats_resp, dict) else {}
            if isinstance(stats_data, dict):
                v = stats_data.get("week52High")
                if v is not None:
                    week_52_high = round(float(v), 2)
                v = stats_data.get("week52Low")
                if v is not None:
                    week_52_low  = round(float(v), 2)
        except Exception as e:
            print(f"[Fugle] stats {ticker} 失敗: {e}")

        # Fugle corporate actions dividends：近一年現金股利加總算殖利率
        if price:
            try:
                one_year_ago  = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
                three_mo_later = (date.today() + timedelta(days=90)).strftime("%Y-%m-%d")
                div_resp = fugle_client.stock.corporate_actions.dividends(
                    symbol=ticker, start_date=one_year_ago, end_date=three_mo_later
                )
                div_data = div_resp.get("data", div_resp) if isinstance(div_resp, dict) else []
                if not isinstance(div_data, list):
                    div_data = []
                # 加總近一年現金股利（API 回傳全市場資料，需過濾 symbol）
                total_cash = 0.0
                for row in div_data:
                    if row.get("symbol") != ticker:
                        continue
                    for key in ("cashDividend", "cash", "dividendCash", "cashEarning"):
                        v = row.get(key)
                        if v is not None:
                            total_cash += float(v)
                            break
                if total_cash > 0:
                    dividend_yield = round(total_cash / price * 100, 2)
            except Exception as e:
                print(f"[Fugle] dividends {ticker} 失敗: {e}")

    # 52週高低由 Fugle stats 提供，不再呼叫 yfinance（避免 rate limit）

    # 名稱：ETF 手動表 → Fugle ticker → Fugle quote → TWSE 清單 → 代號本身
    is_etf = ticker in ETF_NAMES
    fugle_name = fugle_t.get("name") or fugle_q.get("name")
    display_name = (
        ETF_NAMES.get(ticker) if is_etf
        else fugle_name or _tw_stock_names.get(ticker)
    ) or ticker

    # 產業別：ETF 固定 → 手動覆寫表 → Fugle ticker（代碼轉中文）→ TWSE 清單
    fugle_industry_raw = fugle_t.get("industry")
    # Fugle 可能回傳數字代碼（如 "25"），需對應中文名稱
    fugle_industry = TWSE_INDUSTRY_CODE_MAP.get(str(fugle_industry_raw), fugle_industry_raw) if fugle_industry_raw else None
    industry = (
        "ETF 指數股票型基金" if is_etf
        else TICKER_INDUSTRY_OVERRIDE.get(ticker)
        or fugle_industry
        or _tw_stock_industry.get(ticker)
    )

    result = {
        "ticker":         ticker,
        "name":           display_name,
        "price":          price,
        "change":         fugle_q.get("change"),
        "change_pct":     fugle_q.get("change_pct"),
        "dividend_yield": dividend_yield,
        "volume":         volume,
        "volume_zhang":   volume_zhang,
        "week_52_high":   week_52_high,
        "week_52_low":    week_52_low,
        "industry":       industry,
        "source":         price_source,
        "is_attention":             fugle_t.get("is_attention",             False),
        "is_disposition":           fugle_t.get("is_disposition",           False),
        "is_halted":                fugle_t.get("is_halted",                False),
        "is_unusually_recommended": fugle_t.get("is_unusually_recommended", False),
        "is_specific_abnormally":   fugle_t.get("is_specific_abnormally",   False),
    }
    _cache_set(_info_cache, ticker, result)
    # 寫入 SQLite meta 快取（名稱、產業、交易所）
    try:
        parent_ind = TICKER_INDUSTRY_OVERRIDE.get(ticker) and _tw_stock_industry.get(ticker)
        save_stock_meta(ticker, display_name, industry, exchange, parent_ind)
    except Exception:
        pass
    return result


def get_stocks_by_industry(industry_zh: str, exclude_ticker: str = None) -> list:
    """找出相同產業的其他股票。
    優先從 DB 直接回傳（昨收價），不打外部 API。
    細分類無資料時退到上層 TWSE 產業，最後才退到 DEFAULT_TICKERS + 即時 API。
    """
    from app.db import get_industry_stocks_with_price, get_tickers_by_industry, get_parent_industry, _get_parent_from_industry
    _load_tw_stock_names()

    # 快速路徑：DB 直接回傳細分類（含昨收價）
    db_results = get_industry_stocks_with_price(industry_zh, exclude_ticker, limit=40)
    if len(db_results) >= 3:
        return db_results

    # 細分類結果不足（如「記憶體IC」），從 DB 查這個細分類的 parent_industry
    parent = (
        get_parent_industry(exclude_ticker) if exclude_ticker else None
    ) or _tw_stock_industry.get(exclude_ticker or "")
    # 若 exclude_ticker 查不到，改從 DB 找同 industry 的任一筆的 parent
    if not parent:
        parent = _get_parent_from_industry(industry_zh)
    if parent and parent != industry_zh:
        db_results = get_industry_stocks_with_price(parent, exclude_ticker, limit=40)
        if len(db_results) >= 3:
            return db_results

    # 最後退到 DEFAULT_TICKERS，打即時 API
    candidates = [t for t in DEFAULT_TICKERS if t != exclude_ticker]

    def _fetch(ticker):
        try:
            info = get_stock_info(ticker)
            return info if info.get("price") else None
        except Exception:
            return None

    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        for info in pool.map(_fetch, candidates[:40]):
            if info:
                results.append(info)
    return results


MA_PERIODS = {
    "ma5":   {"days": 5,   "label": "週線(MA5)"},
    "ma20":  {"days": 20,  "label": "月線(MA20)"},
    "ma60":  {"days": 60,  "label": "季線(MA60)"},
    "ma240": {"days": 240, "label": "年線(MA240)"},
    "ema60": {"days": 60,  "label": "EMA60", "ema": True},
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


def _fill_recent_gap(ticker: str, last_date: str) -> list:
    """補 last_date 之後的缺口 K 棒：Fugle historical → TWSE 月報 → yfinance。"""
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    bars = []
    print(f"[gap fill] {ticker}: last={last_date} today={today_str}")

    # 1) Fugle historical（有 API Key，不受 IP 限制）
    try:
        gap = _fugle_candles(ticker, last_date, today_str)
        fugle_dates = [r["date"] for r in gap]
        print(f"[gap fill] Fugle dates={fugle_dates}")
        bars = [r for r in gap if r["date"] > last_date]
    except Exception as e:
        print(f"[gap fill] Fugle 失敗: {e}")

    # 2) TWSE/TPEx 月報（涵蓋當月最新資料，Fugle T+0 延遲時特別有用）
    if not bars:
        _load_tw_stock_names()
        exchange = _tw_stock_exchange.get(ticker, "TW")
        # 抓最近兩個月（跨月情境：last_date 在上月，今天在本月）
        months_to_try = set()
        last_dt = date.fromisoformat(last_date)
        cur = last_dt.replace(day=1)
        while cur <= today:
            months_to_try.add((cur.year, cur.month))
            next_month = cur.month % 12 + 1
            next_year = cur.year + (1 if cur.month == 12 else 0)
            cur = cur.replace(year=next_year, month=next_month)
        twse_rows: list = []
        for y, m in sorted(months_to_try):
            twse_rows.extend(_fetch_twse_month(ticker, y, m, exchange))
        twse_new = [r for r in twse_rows if r["date"] > last_date]
        if twse_new:
            print(f"[gap fill] TWSE dates={[r['date'] for r in twse_new]}")
            bars = twse_new
        else:
            print(f"[gap fill] TWSE 無新資料（exchange={exchange}）")

    # 3) yfinance fallback
    if not bars:
        try:
            sym  = _get_symbol(ticker)
            hist = yf.Ticker(sym).history(period="5d", interval="1d")
            if not hist.empty:
                # 注意：須用 tz_localize(None) 保留台北本地日期，
                # 若用 tz_convert(None) 會先轉 UTC 再去時區，午夜 00:00+08:00
                # 會變成前一天 16:00，日期整個錯位一天
                if hist.index.tz is not None:
                    hist.index = hist.index.tz_localize(None)
                yf_dates = [d.strftime("%Y-%m-%d") for d in hist.index]
                print(f"[gap fill] yfinance dates={yf_dates}")
                for d, r in hist.iterrows():
                    d_str = d.strftime("%Y-%m-%d")
                    if d_str > last_date:
                        bars.append({
                            "date":   d_str,
                            "open":   round(float(r["Open"]),  2),
                            "high":   round(float(r["High"]),  2),
                            "low":    round(float(r["Low"]),   2),
                            "close":  round(float(r["Close"]), 2),
                            "volume": int(r["Volume"]),
                        })
        except Exception as e:
            print(f"[gap fill] yfinance 失敗: {e}")

    print(f"[gap fill] {ticker}: result={[r['date'] for r in bars]}")
    return bars


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


def _resample_candles(records: list, interval: str) -> list:
    """將日K重採樣為週K或月K。"""
    if interval not in ("1wk", "1mo") or not records:
        return records
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    rule = "W-FRI" if interval == "1wk" else "ME"
    df = df.resample(rule).agg(
        Open=("Open", "first"), High=("High", "max"),
        Low=("Low", "min"),   Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).dropna(subset=["Open"])
    return [
        {"date": d.strftime("%Y-%m-%d"), "open": round(r.Open, 2),
         "high": round(r.High, 2), "low": round(r.Low, 2),
         "close": round(r.Close, 2), "volume": int(r.Volume)}
        for d, r in df.iterrows()
    ]


def get_stock_history(ticker: str, period: str = "3mo", interval: str = "1d") -> list:
    """取得個股歷史日K。
    優先使用 Fugle historical candles，失敗則退回 TWSE/TPEx 月報，再退回 yfinance。
    """
    cache_key = (ticker, period, interval)
    cached = _cache_get(_history_cache, cache_key, HISTORY_TTL)
    if cached is not None:
        return cached

    # 分鐘線（1m/5m/15m/60m）：回傳真正的 UTC Unix timestamp，前端以本地時間（UTC+8）顯示
    if interval in ("1m", "5m", "15m", "60m"):
        try:
            symbol = _get_symbol(ticker)
            hist = yf.Ticker(symbol).history(period=period, interval=interval)
            if not hist.empty:
                if hist.index.tz is None:
                    hist.index = hist.index.tz_localize("Asia/Taipei")
                else:
                    hist.index = hist.index.tz_convert("Asia/Taipei")
                all_records = [
                    {
                        "date":   int(d.timestamp()),  # UTC+8 timestamp
                        "open":   round(float(r["Open"]),  2),
                        "high":   round(float(r["High"]),  2),
                        "low":    round(float(r["Low"]),   2),
                        "close":  round(float(r["Close"]), 2),
                        "volume": int(r["Volume"]),
                    }
                    for d, r in hist.iterrows()
                ]
        except Exception as e:
            print(f"[yfinance] {interval} history {ticker} 失敗: {e}")
        _cache_set(_history_cache, cache_key, all_records)
        return all_records

    _load_tw_stock_names()
    all_records: list = []

    # 0) SQLite K 線快取（日K 且資料夠新、筆數足夠才回傳）
    if interval == "1d":
        days_needed_pre = _PERIOD_DAYS.get(period, 90)
        from_pre = (date.today() - timedelta(days=days_needed_pre)).strftime("%Y-%m-%d")
        to_pre   = date.today().strftime("%Y-%m-%d")
        # 預期交易日數：自然天數 × 5/7，至少要有 70% 才算資料足夠
        expected_bars = max(5, int(days_needed_pre * 5 / 7 * 0.7))
        if is_candles_fresh(ticker, from_pre, to_pre):
            db_records = get_candles(ticker, from_pre, to_pre)
            if len(db_records) >= expected_bars:
                db_records = list(db_records)
                today_str = date.today().strftime("%Y-%m-%d")
                # 若最後一根不是今天，用 yfinance 補近期缺口（最可靠的近期來源）
                if db_records[-1]["date"] < today_str:
                    _new = _fill_recent_gap(ticker, db_records[-1]["date"])
                    if _new:
                        db_records.extend(_new)
                        db_records.sort(key=lambda x: x["date"])
                        save_candles(ticker, _new)
                # 盤中即時 K 棒（quote_date 必須等於今天，避免颱風假日補假棒）
                if date.today().weekday() < 5 and db_records[-1]["date"] != today_str:
                    q = _fugle_quote(ticker)
                    if q.get("open") and q.get("price") and q.get("quote_date") == today_str:
                        db_records.append({
                            "date":   today_str,
                            "open":   q["open"],
                            "high":   q.get("high") or q["price"],
                            "low":    q.get("low")  or q["price"],
                            "close":  q["price"],
                            "volume": q.get("volume") or 0,
                        })
                _cache_set(_history_cache, cache_key, db_records)
                return db_records

    # 1) Fugle historical candles（API 限制：日期範圍必須 < 365 天）
    days_needed  = _PERIOD_DAYS.get(period, 90)
    to_dt        = date.today()
    fugle_days   = min(days_needed, 364)   # Fugle 要求嚴格小於一年
    fugle_from   = to_dt - timedelta(days=fugle_days)
    fugle_data   = _fugle_candles(ticker, fugle_from.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d"))
    if fugle_data:
        all_records = fugle_data

    # 2) 退回 TWSE/TPEx 月報 API（上市/上櫃各試一次避免交易所辨識錯誤）
    if not all_records:
        exchange      = _tw_stock_exchange.get(ticker, "TW")
        months_needed = _PERIOD_MONTHS.get(period, 3)
        today_ts      = pd.Timestamp.now()
        for i in range(months_needed):
            target = today_ts - pd.DateOffset(months=i)
            all_records.extend(_fetch_twse_month(ticker, target.year, target.month, exchange))
            if i < months_needed - 1:
                time.sleep(0.2)
        all_records.sort(key=lambda x: x["date"])

        # 若仍空白，換另一個交易所再試一次
        if not all_records:
            alt_exchange = "TWO" if exchange == "TW" else "TW"
            for i in range(months_needed):
                target = today_ts - pd.DateOffset(months=i)
                all_records.extend(_fetch_twse_month(ticker, target.year, target.month, alt_exchange))
                if i < months_needed - 1:
                    time.sleep(0.2)
            if all_records:
                _tw_stock_exchange[ticker] = alt_exchange  # 更新正確的交易所
            all_records.sort(key=lambda x: x["date"])

    # 3) yfinance fallback（歷史資料不受地區限制）
    if not all_records:
        try:
            symbol = _get_symbol(ticker)
            hist = yf.Ticker(symbol).history(period=period, interval=interval)
            if not hist.empty:
                hist.index = hist.index.tz_localize(None)
                all_records = [
                    {
                        "date":   d.strftime("%Y-%m-%d"),
                        "open":   round(float(r["Open"]),  2),
                        "high":   round(float(r["High"]),  2),
                        "low":    round(float(r["Low"]),   2),
                        "close":  round(float(r["Close"]), 2),
                        "volume": int(r["Volume"]),
                    }
                    for d, r in hist.iterrows()
                ]
                print(f"[yfinance] history fallback {ticker}: {len(all_records)} 筆")
        except Exception as e:
            print(f"[yfinance] history {ticker} 失敗: {e}")

    all_records = _resample_candles(all_records, interval)

    # 寫入 SQLite K 線快取（僅日K，不含今日未收盤資料）
    if interval == "1d" and all_records:
        try:
            save_candles(ticker, all_records)
        except Exception:
            pass

    # 補近期缺口：若最後一根不是今天，用 yfinance 補最近 5 天（最可靠的近期資料來源）
    if interval == "1d" and all_records:
        today_str = date.today().strftime("%Y-%m-%d")
        if all_records[-1]["date"] < today_str:
            new_bars = _fill_recent_gap(ticker, all_records[-1]["date"])
            if new_bars:
                all_records.extend(new_bars)
                all_records.sort(key=lambda x: x["date"])
    # 盤中即時 K 棒（yfinance 無當日未收盤資料，改用 Fugle intraday quote）
    if interval == "1d" and all_records and date.today().weekday() < 5:
        today_str = date.today().strftime("%Y-%m-%d")
        if all_records[-1]["date"] != today_str:
            q = _fugle_quote(ticker)
            # 颱風假日或休市日：Fugle 回傳的 quote_date 是上一個交易日，不補今日假 K 棒
            if q.get("open") and q.get("price") and q.get("quote_date") == today_str:
                all_records.append({
                    "date":   today_str,
                    "open":   q["open"],
                    "high":   q.get("high") or q["price"],
                    "low":    q.get("low")  or q["price"],
                    "close":  q["price"],
                    "volume": q.get("volume") or 0,
                })

    _cache_set(_history_cache, cache_key, all_records)
    return all_records


def _get_closes_from_db(ticker: str, min_days: int = 20) -> list | None:
    """從 DB 取近 100 個自然日的收盤價，不足 min_days 筆則回 None。"""
    from app.db import get_candles
    from_date = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")
    records   = get_candles(ticker, from_date, to_date)
    if not records:
        return None
    closes = [r["close"] for r in records if r["close"] is not None]
    return closes if len(closes) >= min_days else None


def _get_weekly_change(ticker: str, db_only: bool = False):
    """計算週漲幅：本週收盤 vs 上週五收盤。優先 DB → Fugle → yfinance。"""
    # 1) DB
    closes = _get_closes_from_db(ticker, min_days=10)
    if closes:
        from_date = (date.today() - timedelta(days=50)).strftime("%Y-%m-%d")
        to_date   = date.today().strftime("%Y-%m-%d")
        from app.db import get_candles
        records = get_candles(ticker, from_date, to_date)
        if records:
            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            weekly = df["close"].resample("W-FRI").last().dropna()
            if len(weekly) >= 2:
                return round((weekly.iloc[-1] - weekly.iloc[-2]) / weekly.iloc[-2] * 100, 2)

    if db_only:
        return None

    # 2) Fugle
    to_dt   = date.today()
    from_dt = to_dt - timedelta(days=40)
    candles = _fugle_candles(ticker, from_dt.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d"))
    if candles:
        df = pd.DataFrame(candles)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        weekly = df["close"].resample("W-FRI").last().dropna()
        if len(weekly) >= 2:
            return round((weekly.iloc[-1] - weekly.iloc[-2]) / weekly.iloc[-2] * 100, 2)

    # 3) yfinance fallback
    try:
        symbol = _get_symbol(ticker)
        hist   = yf.Ticker(symbol).history(period="1mo")
        if hist.empty:
            return None
        weekly = hist["Close"].resample("W-FRI").last().dropna()
        if len(weekly) < 2:
            return None
        return round((weekly.iloc[-1] - weekly.iloc[-2]) / weekly.iloc[-2] * 100, 2)
    except Exception:
        return None


def scan_all_weekly_surge(min_weekly_change: float = 20.0,
                          min_volume: float = None,
                          min_capital: float = None) -> list:
    """
    全市場批次掃描週漲幅，全部從 DB 讀取（收盤後使用）。
    Step 1: 從 DB 取近 50 天 K 線，計算週漲幅。
    Step 2: 符合門檻者再從 DB 取 volume/capital 篩選，Fugle 補即時股價。
    """
    from app.db import get_all_candles_in_range

    def is_regular(code: str) -> bool:
        return code.isdigit() and 4 <= len(code) <= 5

    from_date = (date.today() - timedelta(days=50)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")

    _load_tw_stock_names()

    # 一次 SQL 取所有股票 50 天 K 線
    all_candles = get_all_candles_in_range(from_date, to_date)

    def _weekly_chg(records):
        """純 Python 按 ISO 週分組，取最後兩週收盤算漲幅。"""
        from datetime import datetime as _dt
        week_close: dict = {}
        for r in records:
            c = r.get("close")
            if not c:
                continue
            d = _dt.strptime(r["date"], "%Y-%m-%d")
            wk = d.isocalendar()[:2]          # (year, week)
            week_close[wk] = c                 # 每週最後一筆覆蓋
        if len(week_close) < 2:
            return None
        weeks = sorted(week_close)
        prev, last = week_close[weeks[-2]], week_close[weeks[-1]]
        return round((last - prev) / prev * 100, 2) if prev else None

    weekly_map: dict = {}
    for ticker, records in all_candles.items():
        if not is_regular(ticker) or len(records) < 5:
            continue
        chg = _weekly_chg(records)
        if chg is not None and chg >= min_weekly_change:
            weekly_map[ticker] = (chg, records)

    results = []
    for ticker, (wchg, recs) in sorted(weekly_map.items(), key=lambda x: -x[1][0]):
        try:
            last  = recs[-1]
            prev  = recs[-2] if len(recs) >= 2 else last
            close = last.get("close")
            vol   = last.get("volume")
            if not close:
                continue
            vol_zhang  = round(int(vol) / 1000) if vol else None
            change_pct = round((close - prev["close"]) / prev["close"] * 100, 2) if prev["close"] else None
            capital_raw = _tw_stock_capital.get(ticker)
            capital_yi  = round(capital_raw / 1e8, 2) if capital_raw else None

            if min_volume and (vol_zhang is None or vol_zhang < min_volume):
                continue
            if min_capital and (capital_yi is None or capital_yi < min_capital):
                continue

            results.append({
                "ticker":            ticker,
                "name":              _tw_stock_names.get(ticker, ""),
                "price":             round(float(close), 2),
                "change_pct":        change_pct,
                "volume_zhang":      vol_zhang,
                "capital_yi":        capital_yi,
                "weekly_change_pct": wchg,
                "exchange":          _tw_stock_exchange.get(ticker, ""),
            })
        except Exception:
            pass

    return sorted(results, key=lambda x: x.get("weekly_change_pct", 0), reverse=True)


def _calc_ma(ticker: str, ma_key: str, db_only: bool = False):
    """計算指定均線，回傳 (目前股價, MA值, 偏離%) 或 None。優先 DB（MA≤60），MA240 用 yfinance。"""
    cfg = MA_PERIODS[ma_key]
    days = cfg["days"]
    is_ema = cfg.get("ema", False)

    # 1) DB（3個月約63交易日，足夠 MA5/MA20/MA60/EMA60）
    if days <= 60:
        closes_list = _get_closes_from_db(ticker, min_days=days)
        if closes_list:
            closes = pd.Series(closes_list)
            if is_ema:
                ma_value = round(float(closes.ewm(span=days, adjust=False).mean().iloc[-1]), 2)
            else:
                ma_value = round(float(closes.values[-days:].mean()), 2)
            current_price = round(float(closes.values[-1]), 2)
            deviation_pct = round((current_price - ma_value) / ma_value * 100, 2)
            return {"price": current_price, "ma": ma_value, "deviation_pct": deviation_pct}

    if db_only:
        return None

    # 2) yfinance fallback（MA240 或 DB 不足）
    needed_period = "1y" if days <= 60 else "2y"
    symbol = _get_symbol(ticker)
    hist = yf.Ticker(symbol).history(period=needed_period)
    if hist.empty or len(hist) < days:
        return None
    closes = hist["Close"]
    if is_ema:
        ma_value = round(float(closes.ewm(span=days, adjust=False).mean().iloc[-1]), 2)
    else:
        ma_value = round(float(closes.values[-days:].mean()), 2)
    current_price = round(float(closes.values[-1]), 2)
    deviation_pct = round((current_price - ma_value) / ma_value * 100, 2)
    return {"price": current_price, "ma": ma_value, "deviation_pct": deviation_pct}


def _calc_ma_squeeze(closes_list: list) -> bool:
    """
    MA 黏合型態（先發散再收斂）：
    1. 目前 MA5 在 MA20 上方，差距 < 3%（正在黏合）
    2. 近 15 天內曾大幅發散（gap 曾 > 5%），確認有過上漲動能後回落
    3. 近 15 天 MA5 從未低於 MA20（全程在上方）
    """
    if len(closes_list) < 40:
        return False
    closes = pd.Series(closes_list)
    ma5  = closes.rolling(5).mean().dropna().values
    ma20 = closes.rolling(20).mean().dropna().values
    n    = min(len(ma5), len(ma20))
    ma5, ma20 = ma5[-n:], ma20[-n:]
    gaps = (ma5 - ma20) / ma20
    cur     = gaps[-1]
    recent  = gaps[-15:]
    if not (0 < cur < 0.03):
        return False
    if max(recent) < 0.05:
        return False
    if min(recent) < 0:
        return False
    # 收盤價必須在 MA5 之上（排除股價跌穿 MA5 導致的假性黏合）
    if closes_list[-1] < ma5[-1]:
        return False
    return True


def scan_near_ema60(limit: int = 500) -> list:
    """掃全市場，回傳收盤價在 EMA60 上方 0~3% 內、日量 ≥ 2000 張、非金融保險的股票。"""
    from app.db import get_all_db_tickers_with_meta, get_candles
    from datetime import date, timedelta

    from_date = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")

    all_tickers = get_all_db_tickers_with_meta()
    results = []
    for row in all_tickers:
        ticker = row["ticker"]
        if row.get("parent_industry") == "金融保險":
            continue
        records = get_candles(ticker, from_date, to_date)
        if not records or len(records) < 62:
            continue
        last = records[-1]
        vol_shares = last.get("volume") or 0
        if vol_shares < 2_000_000:
            continue
        closes = [r["close"] for r in records if r["close"] is not None]
        # 逐日計算 EMA60，保留最後 20 個交易日的 EMA 值
        k, ema = 2 / 61, None
        ema_series = []
        for c in closes:
            ema = c if ema is None else c * k + ema * (1 - k)
            ema_series.append(ema)
        close = last.get("close")
        if not close or not ema:
            continue
        dev = (close - ema) / ema
        if not (0 <= dev <= 0.03):
            continue
        # 近 20 個交易日（約一個月）的收盤都必須在當日 EMA60 上方
        recent_closes = closes[-20:]
        recent_emas   = ema_series[-20:]
        if any(c < e for c, e in zip(recent_closes, recent_emas)):
            continue
        prev = records[-2] if len(records) >= 2 else last
        prev_close = prev.get("close")
        change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else None
        results.append({
            "ticker":       ticker,
            "name":         row.get("name") or "",
            "exchange":     row.get("exchange") or "",
            "close":        round(float(close), 2),
            "change_pct":   change_pct,
            "volume_zhang": round(vol_shares / 1000),
            "ema60":        round(float(ema), 2),
            "dev_pct":      round(dev * 100, 2),
        })
        if len(results) >= limit:
            break
    return results


def _detect_ma_pattern(ticker: str) -> dict:
    """偵測 MA 黏合型態（從 DB 優先，fallback yfinance）。"""
    from app.db import get_candles
    from datetime import date, timedelta
    from_date = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")
    records   = get_candles(ticker, from_date, to_date)
    if records:
        closes_list = [r["close"] for r in records if r["close"] is not None]
    else:
        # fallback yfinance
        hist = yf.Ticker(_get_symbol(ticker)).history(period="3mo")
        closes_list = list(hist["Close"].values) if not hist.empty else []
    result = _calc_ma_squeeze(closes_list)
    return {"bird_beak": result, "divergence": result}


def scan_ma_squeeze(limit: int = 200) -> list:
    """掃全市場（DB 內所有有 K 線的股票），回傳符合 MA 黏合條件的股票清單。"""
    from app.db import get_all_db_tickers_with_meta, get_candles
    from datetime import date, timedelta
    from_date = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")

    all_tickers = get_all_db_tickers_with_meta()
    results = []
    for row in all_tickers:
        ticker = row["ticker"]
        if row.get("parent_industry") == "金融保險":
            continue
        records = get_candles(ticker, from_date, to_date)
        if not records:
            continue
        closes_list = [r["close"] for r in records if r["close"] is not None]
        if not _calc_ma_squeeze(closes_list):
            continue
        last = records[-1]
        # 日成交量 < 2000 張略過
        vol_shares = last.get("volume") or 0
        if vol_shares < 2_000_000:
            continue
        prev = records[-2] if len(records) >= 2 else last
        close = last.get("close")
        prev_close = prev.get("close")
        change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else None
        results.append({
            "ticker":       ticker,
            "name":         row.get("name") or "",
            "exchange":     row.get("exchange") or "",
            "close":        round(float(close), 2) if close else None,
            "change_pct":   change_pct,
            "volume_zhang": round(vol_shares / 1000),
            "pattern":      "bird_beak",
        })
        if len(results) >= limit:
            break
    return results


def _check_technical_signals(ticker: str, db_only: bool = False) -> dict | None:
    """計算技術訊號（前日漲幅、MA20方向、收盤與MA5/MA60相對位置）。優先 DB → yfinance。"""
    # 1) DB（需 ≥65 筆，約 3 個月）
    closes_list = _get_closes_from_db(ticker, min_days=65)
    if closes_list:
        closes = pd.Series(closes_list)
        prev_close  = float(closes.iloc[-1])
        prev2_close = float(closes.iloc[-2])
        ma5  = closes.rolling(5).mean()
        ma20 = closes.rolling(20).mean()
        ma60 = closes.rolling(60).mean()
        return {
            "prev_day_change_pct": round((prev_close - prev2_close) / prev2_close * 100, 2),
            "ma20_rising":         float(ma20.iloc[-1]) > float(ma20.iloc[-2]),
            "price_above_ma5":     prev_close > float(ma5.iloc[-1]),
            "price_above_ma60":    prev_close > float(ma60.iloc[-1]),
        }

    if db_only:
        return None

    # 2) yfinance fallback
    symbol = _get_symbol(ticker)
    try:
        hist = yf.Ticker(symbol).history(period="1y")
    except Exception:
        return None
    if hist.empty or len(hist) < 65:
        return None
    closes = hist["Close"]
    prev_close  = float(closes.iloc[-1])
    prev2_close = float(closes.iloc[-2])
    ma5  = closes.rolling(5).mean()
    ma20 = closes.rolling(20).mean()
    ma60 = closes.rolling(60).mean()
    return {
        "prev_day_change_pct": round((prev_close - prev2_close) / prev2_close * 100, 2),
        "ma20_rising":         float(ma20.iloc[-1]) > float(ma20.iloc[-2]),
        "price_above_ma5":     prev_close > float(ma5.iloc[-1]),
        "price_above_ma60":    prev_close > float(ma60.iloc[-1]),
    }


def _get_info_from_db(ticker: str) -> dict | None:
    """從 DB candles + meta 取得基本資訊，不打外部 API。
    price/volume 用最後一筆收盤，capital 用 _tw_stock_capital。
    """
    from app.db import get_candles, get_all_db_tickers_with_meta
    from datetime import date, timedelta
    _load_tw_stock_names()
    from_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")
    rows = get_candles(ticker, from_date, to_date)
    if not rows:
        return None
    last = rows[-1]
    price = last.get("close")
    if not price:
        return None
    volume_raw   = last.get("volume") or 0       # 股數
    volume_zhang = round(volume_raw / 1000)
    capital_raw  = _tw_stock_capital.get(ticker)  # NT$元
    capital_yi   = round(capital_raw / 1e8, 2) if capital_raw else None
    name     = _tw_stock_names.get(ticker, ticker)
    exchange = _tw_stock_exchange.get(ticker, "TW")
    prev_close = rows[-2].get("close") if len(rows) >= 2 else None
    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else None
    return {
        "ticker":      ticker,
        "name":        name,
        "price":       round(float(price), 2),
        "change_pct":  change_pct,
        "volume_zhang": volume_zhang,
        "capital_yi":  capital_yi,
        "exchange":    exchange,
        "pe_ratio":    None,
        "dividend_yield": None,
        "market_cap_yi":  None,
    }


def screen_stocks(tickers: list, filters: dict) -> list:
    """根據條件篩選股票。tickers 為空時掃全部 DB 股票（使用 DB 資料，不打外部 API）。"""
    from app.db import get_all_db_tickers_with_meta
    near_ma         = filters.get("near_ma")
    near_ma_pct     = filters.get("near_ma_pct", 3.0)
    pattern         = filters.get("pattern")
    min_weekly_chg  = filters.get("min_weekly_change")

    use_db = not tickers
    meta_name_db = {}
    if use_db:
        meta_list    = get_all_db_tickers_with_meta()
        tickers      = [m["ticker"] for m in meta_list]
        meta_name_db = {m["ticker"]: m.get("name") for m in meta_list if m.get("name")}

    results = []
    for ticker in tickers:
        try:
            info = _get_info_from_db(ticker) if use_db else get_stock_info(ticker)
            if info is None:
                continue
            # 用 stock_meta DB 的名字補正（避免 _tw_stock_names API 載入失敗時顯示代號）
            if use_db and meta_name_db.get(ticker):
                info["name"] = meta_name_db[ticker]
            if not _passes_basic_filters(info, filters):
                continue

            # 週漲幅篩選（需額外抓 10d 歷史，但比均線快）
            if min_weekly_chg is not None:
                wchg = _get_weekly_change(ticker, db_only=use_db)
                if wchg is None or wchg < min_weekly_chg:
                    continue
                info["weekly_change_pct"] = wchg

            # 均線位置篩選
            if near_ma and near_ma in MA_PERIODS:
                ma_data = _calc_ma(ticker, near_ma, db_only=use_db)
                if ma_data is None:
                    continue
                if not (0 <= ma_data["deviation_pct"] <= near_ma_pct):
                    continue
                info["ma_value"] = ma_data["ma"]
                info["ma_deviation_pct"] = ma_data["deviation_pct"]
                info["ma_label"] = MA_PERIODS[near_ma]["label"]

            # 技術面訊號篩選（前日漲幅、MA20方向、收盤位置）
            needs_tech = (
                filters.get("min_prev_day_change") is not None
                or filters.get("ma20_rising")
                or filters.get("price_above_ma5_ma60")
            )
            if needs_tech:
                tech = _check_technical_signals(ticker, db_only=use_db)
                if tech is None:
                    continue
                if filters.get("min_prev_day_change") is not None:
                    if tech["prev_day_change_pct"] < filters["min_prev_day_change"]:
                        continue
                if filters.get("ma20_rising") and not tech["ma20_rising"]:
                    continue
                if filters.get("price_above_ma5_ma60"):
                    if not (tech["price_above_ma5"] and tech["price_above_ma60"]):
                        continue

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


_ranking_cache: dict = {}
RANKING_TTL = 300  # 5 分鐘（Fugle 即時資料不用快取太久）


def _parse_num(s) -> float | None:
    if not s:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("+", "-", "--", ""):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _fugle_snapshot_actives(market: str) -> list:
    """用 Fugle snapshot/actives 取得即時成交值排行（盤中/收盤皆可）"""
    client = _get_fugle()
    if not client:
        return []
    try:
        resp = client.stock.snapshot.actives(
            market=market, trade="value", type="ALLBUT0999"
        )
        data = resp.get("data", []) if isinstance(resp, dict) else []
        label = "上市" if market == "TSE" else "上櫃"
        results = []
        for item in data:
            tv  = item.get("tradeValue", 0) or 0
            vol = item.get("tradeVolume", 0) or 0
            close = item.get("closePrice")
            chg   = item.get("change")
            chg_pct = item.get("changePercent")
            results.append({
                "ticker":             item.get("symbol", ""),
                "name":               item.get("name", ""),
                "close":              round(float(close), 2) if close is not None else None,
                "change":             round(float(chg), 2) if chg is not None else None,
                "change_pct":         round(float(chg_pct), 2) if chg_pct is not None else None,
                "trade_value_yi":     round(float(tv) / 1e8, 2),
                "trade_volume_zhang": round(int(vol) / 1000) if vol else None,
                "exchange":           label,
            })
        return results
    except Exception as e:
        print(f"[Fugle] snapshot actives {market} 失敗: {e}")
        return []


def _enrich_with_intraday(stocks: list) -> list:
    """並行為 stocks 補充 intraday 資料：委買、委賣、單量、成交量、漲停跌停旗標。
    結果不影響快取 key，失敗就保留原欄位（留 None）。
    """
    client = _get_fugle()
    if not client or not stocks:
        return stocks

    def _fetch(ticker: str):
        try:
            resp = client.stock.intraday.quote(symbol=ticker)
            data = resp.get("data", resp) if isinstance(resp, dict) else {}
            if not isinstance(data, dict):
                return ticker, {}
            bids = data.get("bids") or []
            asks = data.get("asks") or []
            total = data.get("total") or {}
            last_size = data.get("lastSize")
            ref   = data.get("referencePrice") or 0
            close = data.get("closePrice") or data.get("lastPrice") or 0
            lt       = data.get("lastTrade") or {}
            lt_price = lt.get("price")
            lt_ask   = lt.get("ask")
            lt_bid   = lt.get("bid")
            if lt_price and lt_ask and lt_price >= lt_ask:
                last_dir = "buy"
            elif lt_price and lt_bid and lt_price <= lt_bid:
                last_dir = "sell"
            else:
                last_dir = None

            return ticker, {
                "best_bid":           bids[0]["price"] if bids else None,
                "best_ask":           asks[0]["price"] if asks else None,
                "last_size_zhang":    round(last_size / 1000) if last_size else None,
                "last_trade_dir":     last_dir,
                "trade_volume_zhang": int(total.get("tradeVolume") or 0) or None,
                "is_limit_up":        bool(data.get("isLimitUpPrice")),
                "is_limit_down":      bool(data.get("isLimitDownPrice")),
            }
        except Exception:
            return ticker, {}

    with ThreadPoolExecutor(max_workers=20) as pool:
        quote_map = dict(pool.map(_fetch, [s["ticker"] for s in stocks]))

    merged = []
    for s in stocks:
        q = quote_map.get(s["ticker"], {})
        merged.append({**s, **{k: v for k, v in q.items() if v is not None}})
    return merged


def get_trade_value_ranking(limit: int = 50, force: bool = False) -> list:
    """取得成交值排行（合併上市 + 上櫃）
    優先 Fugle snapshot/actives（盤中即時），退回 TWSE/TPEx 收盤資料。
    """
    if not force:
        cached = _cache_get(_ranking_cache, "trade_value", RANKING_TTL)
        if cached is not None:
            return cached[:limit]

    results = []

    # 1) Fugle snapshot/actives（盤中即時 + 收盤皆可用）
    for market in ("TSE", "OTC"):
        results.extend(_fugle_snapshot_actives(market))

    # 2) 退回收盤資料（TWSE + TPEx 各自獨立抓，不互相依賴）
    if not results:
        try:
            resp = requests.get(
                "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
                timeout=15, headers=_TWSE_HEADERS,
            )
            for row in resp.json():
                code = row.get("Code", "").strip()
                if not code.isdigit() or not (4 <= len(code) <= 5):
                    continue
                tv    = _parse_num(row.get("TradeValue"))
                close = _parse_num(row.get("ClosingPrice"))
                chg   = _parse_num(row.get("Change"))
                vol   = _parse_num(row.get("TradeVolume"))
                if not tv or tv <= 0:
                    continue
                chg_pct = None
                if chg is not None and close is not None and (close - chg) != 0:
                    chg_pct = round(chg / (close - chg) * 100, 2)
                results.append({
                    "ticker":             code,
                    "name":               row.get("Name", "").strip(),
                    "close":              round(close, 2) if close else None,
                    "change":             chg,
                    "change_pct":         chg_pct,
                    "trade_value_yi":     round(tv / 1e8, 2),
                    "trade_volume_zhang": round(vol / 1000) if vol else None,
                    "exchange":           "上市",
                })
        except Exception as e:
            print(f"[TWSE] STOCK_DAY_ALL 失敗: {e}")

        try:
            resp = requests.get(
                "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
                timeout=15, headers=_TWSE_HEADERS,
            )
            rows = resp.json()
            if rows:
                print(f"[TPEx] ranking sample keys: {list(rows[0].keys())[:12]}")
            for row in rows:
                code = row.get("SecuritiesCompanyCode", "").strip()
                if not code.isdigit() or not (4 <= len(code) <= 5):
                    continue
                tv    = _parse_num(row.get("TradingMoney"))
                close = _parse_num(row.get("Close"))
                chg   = _parse_num(row.get("Change"))
                vol   = _parse_num(row.get("TradingShares"))
                if not tv or tv <= 0:
                    continue
                chg_pct = None
                if chg is not None and close is not None and (close - chg) != 0:
                    chg_pct = round(chg / (close - chg) * 100, 2)
                results.append({
                    "ticker":             code,
                    "name":               row.get("CompanyAbbreviation", "").strip(),
                    "close":              round(close, 2) if close else None,
                    "change":             chg,
                    "change_pct":         chg_pct,
                    "trade_value_yi":     round(tv / 1e8, 2),
                    "trade_volume_zhang": round(vol / 1000) if vol else None,
                    "exchange":           "上櫃",
                })
        except Exception as e:
            print(f"[TPEx] daily quotes 失敗: {e}")

    results = [r for r in results if r.get("trade_value_yi", 0) > 0]
    results.sort(key=lambda x: x["trade_value_yi"], reverse=True)
    results = _enrich_with_intraday(results[:limit])

    _cache_set(_ranking_cache, "trade_value", results)
    return results[:limit]


_turnover_cache: dict = {}
TURNOVER_TTL = 300  # 5 分鐘


def get_turnover_ranking(limit: int = 50, force: bool = False) -> list:
    """取得週轉率排行（成交量 ÷ 在外流通股數）
    優先 Fugle snapshot/actives（盤中即時），退回 TWSE/TPEx 收盤資料。
    Fugle tradeVolume 單位：張(lot)
    在外流通股數(張) = 實收資本額(元) / 面額10元 / 1000股/張
    """
    if not force:
        cached = _cache_get(_turnover_cache, "turnover", TURNOVER_TTL)
        if cached is not None:
            return cached[:limit]

    _load_tw_stock_names()
    results = []

    # 1) 優先 Fugle snapshot/actives（今日即時成交量）
    for market in ("TSE", "OTC"):
        label = "上市" if market == "TSE" else "上櫃"
        try:
            client = _get_fugle()
            if client:
                resp = client.stock.snapshot.actives(
                    market=market, trade="volume", type="ALLBUT0999"
                )
                data = resp.get("data", []) if isinstance(resp, dict) else []
                for item in data:
                    code = item.get("symbol", "")
                    vol  = item.get("tradeVolume", 0) or 0
                    if not vol:
                        continue
                    capital = _tw_stock_capital.get(code)
                    if not capital or capital <= 0:
                        continue
                    # Fugle tradeVolume 單位：張；outstanding_zhang = 實收資本額(元)/10(面額)/1000
                    outstanding_zhang = capital / 10_000
                    if outstanding_zhang <= 0:
                        continue
                    turnover_pct = round(float(vol) / outstanding_zhang * 100, 4)
                    if turnover_pct <= 0:
                        continue
                    close   = item.get("closePrice")
                    chg     = item.get("change")
                    chg_pct = item.get("changePercent")
                    results.append({
                        "ticker":             code,
                        "name":               item.get("name", _tw_stock_names.get(code, "")),
                        "close":              round(float(close), 2) if close is not None else None,
                        "change":             round(float(chg), 2) if chg is not None else None,
                        "change_pct":         round(float(chg_pct), 2) if chg_pct is not None else None,
                        "turnover_pct":       turnover_pct,
                        "trade_volume_zhang": int(vol),
                        "exchange":           label,
                    })
        except Exception as e:
            print(f"[Fugle] snapshot actives volume {market} 失敗: {e}")

    if results:
        results.sort(key=lambda x: x["turnover_pct"], reverse=True)
        results = _enrich_with_intraday(results[:limit])
        _cache_set(_turnover_cache, "turnover", results)
        return results[:limit]

    def _to_turnover(code, name, vol, close, chg, chg_pct, exchange):
        capital = _tw_stock_capital.get(code)
        if not capital or capital <= 0 or not vol or vol <= 0:
            return None
        # 實收資本額(千元) × 100 = 在外流通股數（面額 10 元）
        outstanding = capital * 100
        turnover_pct = round(float(vol) / outstanding * 100, 4)
        if turnover_pct <= 0:
            return None
        return {
            "ticker":             code,
            "name":               name,
            "close":              round(float(close), 2) if close is not None else None,
            "change":             round(float(chg), 2) if chg is not None else None,
            "change_pct":         round(float(chg_pct), 2) if chg_pct is not None else None,
            "turnover_pct":       turnover_pct,
            "trade_volume_zhang": round(float(vol) / 1000),
            "exchange":           exchange,
        }

    # 上市 (TWSE)
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            timeout=15, headers=_TWSE_HEADERS,
        )
        for row in resp.json():
            code = row.get("Code", "").strip()
            if not code.isdigit() or not (4 <= len(code) <= 5):
                continue
            vol   = _parse_num(row.get("TradeVolume"))
            close = _parse_num(row.get("ClosingPrice"))
            chg   = _parse_num(row.get("Change"))
            if not vol:
                continue
            chg_pct = None
            if chg is not None and close is not None and (close - chg) != 0:
                chg_pct = round(chg / (close - chg) * 100, 2)
            r = _to_turnover(code, row.get("Name", "").strip(), vol, close, chg, chg_pct, "上市")
            if r:
                results.append(r)
    except Exception as e:
        print(f"[TWSE] STOCK_DAY_ALL turnover 失敗: {e}")

    # 上櫃 (TPEx)
    try:
        resp = requests.get(
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
            timeout=15, headers=_TWSE_HEADERS,
        )
        for row in resp.json():
            code = row.get("SecuritiesCompanyCode", "").strip()
            if not code.isdigit() or not (4 <= len(code) <= 5):
                continue
            vol   = _parse_num(row.get("TradingShares"))
            close = _parse_num(row.get("Close"))
            chg   = _parse_num(row.get("Change"))
            if not vol:
                continue
            chg_pct = None
            if chg is not None and close is not None and (close - chg) != 0:
                chg_pct = round(chg / (close - chg) * 100, 2)
            r = _to_turnover(code, row.get("CompanyAbbreviation", "").strip(), vol, close, chg, chg_pct, "上櫃")
            if r:
                results.append(r)
    except Exception as e:
        print(f"[TPEx] turnover 失敗: {e}")

    results.sort(key=lambda x: x["turnover_pct"], reverse=True)
    results = _enrich_with_intraday(results[:limit])

    _cache_set(_turnover_cache, "turnover", results)
    return results[:limit]


# 委買委賣快照快取（盤中更新，盤後繼續顯示最後快照，保留 24 小時）
_orderbook_snapshot: dict = {}  # ticker → (ts, bids, asks)


def get_stock_orderbook(ticker: str) -> dict:
    """取得委買委賣五檔：盤中即時，盤後顯示最後快照（標記 is_realtime=False）。"""
    empty = {"ticker": ticker, "close": None, "change": None, "change_pct": None,
             "best_bids": [], "best_asks": [], "is_realtime": False}
    client = _get_fugle()
    if not client:
        return empty
    try:
        resp = client.stock.intraday.quote(symbol=ticker)
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        if not isinstance(data, dict):
            data = {}

        price = data.get("closePrice") or data.get("lastPrice") or data.get("referencePrice")
        ref   = data.get("referencePrice")
        change = change_pct = None
        if price and ref:
            change     = round(float(price) - float(ref), 2)
            change_pct = round(change / float(ref) * 100, 2)

        def norm(item):
            return {
                "price": round(float(item.get("price", 0)), 2),
                "size":  int(item.get("size", 0)),
            }

        bids_raw = data.get("bids") or []
        asks_raw = data.get("asks") or []
        bids = [norm(b) for b in bids_raw[:5]]
        asks = [norm(a) for a in asks_raw[:5]]
        is_realtime = bool(bids and asks)

        if is_realtime:
            # 盤中有即時資料 → 更新快照快取
            _orderbook_snapshot[ticker] = (time.time(), bids, asks)
        else:
            # 盤後無資料 → 嘗試使用今日（24 小時內）的最後快照
            cached = _orderbook_snapshot.get(ticker)
            if cached and (time.time() - cached[0]) < 86400:
                _, bids, asks = cached

        return {
            "ticker":      ticker,
            "close":       round(float(price), 2) if price else None,
            "change":      change,
            "change_pct":  change_pct,
            "best_bids":   bids,
            "best_asks":   asks,
            "is_realtime": is_realtime,
        }
    except Exception as e:
        print(f"[Fugle] orderbook {ticker} 失敗: {e}")
        return empty


def get_stock_trades(ticker: str, limit: int = 30) -> list:
    """取得個股成交明細（intraday/trades），收盤後仍保留當日資料。"""
    client = _get_fugle()
    if not client:
        return []
    try:
        resp = client.stock.intraday.trades(symbol=ticker, limit=limit)
        data = resp.get("data", []) if isinstance(resp, dict) else []
        result = []
        for t in (data if isinstance(data, list) else []):
            ts = t.get("time")
            # time 為 microseconds Unix timestamp，轉為 HH:MM:SS
            if ts:
                dt = datetime.fromtimestamp(ts / 1_000_000, tz=timezone.utc).astimezone(
                    __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("Asia/Taipei")
                )
                time_str = dt.strftime("%H:%M:%S")
            else:
                time_str = None
            result.append({
                "time":   time_str,
                "price":  t.get("price"),
                "size":   t.get("size"),   # 單筆張數
                "bid":    t.get("bid"),
                "ask":    t.get("ask"),
            })
        return result
    except Exception as e:
        print(f"[Fugle] trades {ticker} 失敗: {e}")
        return []


def search_stocks(q: str, limit: int = 10) -> list[dict]:
    """模糊搜尋股票代號或名稱，優先使用完整清單，備援靜態表"""
    _load_tw_stock_names()
    q = q.strip()
    if not q:
        return []

    # 合併所有來源：TWSE 完整清單 > 靜態備援表 > ETF
    merged: dict[str, str] = {**COMMON_STOCK_NAMES, **ETF_NAMES}
    merged.update(_tw_stock_names)  # TWSE 清單優先覆蓋

    results = []
    q_lower = q.lower()
    for ticker, name in merged.items():
        if ticker.startswith(q) or q_lower in name.lower():
            results.append({"ticker": ticker, "name": name})
        if len(results) >= limit:
            break
    return results
