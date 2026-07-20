import os
import base64
import tempfile
import threading
import time
import requests
import urllib3
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
            if vol_shares <= 0:
                continue  # 成交量 0 代表當天沒開盤，不算 K 棒
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
_twse_names_loaded = False   # 上市清單是否已成功載入
_tpex_names_loaded = False   # 上櫃清單是否已成功載入（跟上市分開，其中一個失敗不影響另一個重試）
_twse_names_last_try = 0.0
_tpex_names_last_try = 0.0
_NAMES_RETRY_COOLDOWN = 300  # 失敗後至少間隔 5 分鐘才重試，避免對方持續異常時被打爆

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
    """從證交所與櫃買中心抓股票中文名稱、產業別、實收資本額。
    上市／上櫃分開追蹤成功狀態：哪個失敗了，哪個就在冷卻時間過後重試，
    不會因為其中一個掛掉就永遠連累另一個（也不會無限重試打爆對方 API）。
    """
    global _tw_stock_names, _tw_stock_industry, _tw_stock_exchange, _tw_stock_capital
    global _twse_names_loaded, _tpex_names_loaded, _twse_names_last_try, _tpex_names_last_try

    now = time.time()

    # 上市（TWSE）
    if not _twse_names_loaded and now - _twse_names_last_try >= _NAMES_RETRY_COOLDOWN:
        _twse_names_last_try = now
        try:
            rows = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", timeout=10).json()
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
            _twse_names_loaded = True
            print(f"[TWSE] 上市股票清單載入 {len(_tw_stock_names)} 筆，資本額 {len(_tw_stock_capital)} 筆")
        except Exception as e:
            print(f"[TWSE] 上市股票清單載入失敗，{_NAMES_RETRY_COOLDOWN}秒後重試: {e}")

    # 上櫃（TPEx）
    if not _tpex_names_loaded and now - _tpex_names_last_try >= _NAMES_RETRY_COOLDOWN:
        _tpex_names_last_try = now
        try:
            rows = _tpex_get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O").json()
            tpex_count = 0
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
                    tpex_count += 1
                if code and industry_code and code not in _tw_stock_industry:
                    _tw_stock_industry[code] = TWSE_INDUSTRY_CODE_MAP.get(industry_code, industry_code)
                if code and capital_str and code not in _tw_stock_capital:
                    try:
                        _tw_stock_capital[code] = float(capital_str)
                    except ValueError:
                        pass
            _tpex_names_loaded = True
            print(f"[TPEx] 上櫃股票清單載入 {tpex_count} 筆")
        except Exception as e:
            print(f"[TPEx] 上櫃股票清單載入失敗，{_NAMES_RETRY_COOLDOWN}秒後重試: {e}")


_TWSE_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# TPEx 憑證缺少 Subject Key Identifier 擴充欄位，新版 OpenSSL（如 3.5+）驗證會直接拒絕，
# 但 curl 用系統信任鏈驗證是正常的，代表憑證本身可信，只是 Python 比較嚴格。
# 這裡只放寬這個網域的驗證（抓的都是公開股票資料，非敏感資訊）。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _tpex_get(url: str, **kwargs):
    kwargs.setdefault("timeout", 10)
    kwargs.setdefault("verify", False)
    return requests.get(url, **kwargs)


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
    next_ex_dividend_date = None
    next_ex_dividend_cash = None
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

        # Fugle corporate actions dividends：近一年現金股利加總算殖利率，順便找下一次除權息日
        if price:
            try:
                one_year_ago  = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
                three_mo_later = (date.today() + timedelta(days=90)).strftime("%Y-%m-%d")
                today_str = date.today().strftime("%Y-%m-%d")
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
                    row_date = row.get("date")
                    if row_date and row_date >= today_str:
                        if next_ex_dividend_date is None or row_date < next_ex_dividend_date:
                            next_ex_dividend_date = row_date
                            next_ex_dividend_cash = row.get("cashDividend")
                if total_cash > 0:
                    dividend_yield = round(total_cash / price * 100, 2)
            except Exception as e:
                print(f"[Fugle] dividends {ticker} 失敗: {e}")

    # 52週高低由 Fugle stats 提供，不再呼叫 yfinance（避免 rate limit）

    # 本益比/股價淨值比/融資融券：來自每日排程存的 TWSE/TPEx 官方資料（DB-only，不打外部 API）
    from app.db import get_latest_fundamentals, get_latest_margin_trading
    fund   = get_latest_fundamentals(ticker) or {}
    margin = get_latest_margin_trading(ticker) or {}
    pe_ratio = fund.get("pe_ratio")
    pb_ratio = fund.get("pb_ratio")
    # dividend_yield 優先用上面 Fugle 即時股利算出來的值，算不出來才 fallback 用官方數字
    if dividend_yield is None:
        dividend_yield = fund.get("dividend_yield")

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

    # 前一交易日高低（供前端算三關價：上關/中關/下關）
    prev_high = prev_low = None
    try:
        today_str = date.today().strftime("%Y-%m-%d")
        lookback_start = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        prev_bars = [c for c in get_candles(ticker, lookback_start, today_str) if c["date"] < today_str]
        if prev_bars:
            prev_high = prev_bars[-1].get("high")
            prev_low  = prev_bars[-1].get("low")
    except Exception:
        pass

    result = {
        "ticker":         ticker,
        "name":           display_name,
        "price":          price,
        "change":         fugle_q.get("change"),
        "change_pct":     fugle_q.get("change_pct"),
        # 今日開高低 + 報價所屬日期（供前端即時更新股價走勢圖今天這根 K 棒用）
        "open":           fugle_q.get("open"),
        "high":           fugle_q.get("high"),
        "low":            fugle_q.get("low"),
        "prev_high":      prev_high,
        "prev_low":       prev_low,
        "quote_date":     fugle_q.get("quote_date"),
        "dividend_yield": dividend_yield,
        "next_ex_dividend_date": next_ex_dividend_date,
        "next_ex_dividend_cash": next_ex_dividend_cash,
        "pe_ratio":       pe_ratio,
        "pb_ratio":       pb_ratio,
        "margin_balance": margin.get("margin_balance"),
        "margin_quota":   margin.get("margin_quota"),
        "short_balance":  margin.get("short_balance"),
        "short_quota":    margin.get("short_quota"),
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


def _enrich_with_live_quotes(rows: list) -> list:
    """把 DB 查出來的股票清單（只有昨收價）補上即時成交價、漲跌、漲跌幅，供產業個股清單顯示用。"""
    if not rows:
        return rows
    quote_map = {q["ticker"]: q for q in get_watchlist_quotes([r["ticker"] for r in rows])}
    for r in rows:
        q = quote_map.get(r["ticker"], {})
        if q.get("close") is not None:
            r["price"] = q["close"]
        r["change"] = q.get("change")
        r["change_pct"] = q.get("change_pct")
    return rows


def get_stocks_by_industry(industry_zh: str, exclude_ticker: str = None, use_parent: bool = False) -> tuple[list, str]:
    """找出相同產業的其他股票。
    優先從 DB 直接回傳（昨收價），不打外部 API。
    細分類無資料時退到上層 TWSE 產業，最後才退到 DEFAULT_TICKERS + 即時 API。
    use_parent=True 時直接當作 TWSE 產業大分類查（例如產業表現排行點進來的），跳過細分類/模糊比對。
    回傳 (股票清單, 實際使用的產業分類名稱)——細分類結果不足退到大分類時，
    resolved 會是大分類名稱，讓前端能提示使用者顯示範圍已擴大，避免「封裝測試」清單
    卻混入一堆 info.industry 顯示「半導體業」的股票，看起來像資料矛盾。
    """
    from app.db import get_industry_stocks_with_price, get_tickers_by_industry, get_parent_industry, _get_parent_from_industry
    _load_tw_stock_names()

    if use_parent:
        db_results = get_industry_stocks_with_price(industry_zh, exclude_ticker, limit=100, use_parent=True)
        return _enrich_with_live_quotes(db_results), industry_zh

    # 快速路徑：DB 直接回傳細分類（含昨收價）
    db_results = get_industry_stocks_with_price(industry_zh, exclude_ticker, limit=40)
    if len(db_results) >= 3:
        return _enrich_with_live_quotes(db_results), industry_zh

    # 細分類結果不足（如「記憶體IC」），從 DB 查這個細分類的 parent_industry
    parent = (
        get_parent_industry(exclude_ticker) if exclude_ticker else None
    ) or _tw_stock_industry.get(exclude_ticker or "")
    # 若 exclude_ticker 查不到，改從 DB 找同 industry 的任一筆的 parent
    if not parent:
        parent = _get_parent_from_industry(industry_zh)
    if parent and parent != industry_zh:
        db_results = get_industry_stocks_with_price(parent, exclude_ticker, limit=40, use_parent=True)
        if len(db_results) >= 3:
            return _enrich_with_live_quotes(db_results), parent

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
    return results, industry_zh


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
                    vol = int(r["Volume"])
                    # 成交量 0 代表當天沒有真正開盤交易（假日佔位資料），不算 K 棒
                    if d_str > last_date and vol > 0:
                        bars.append({
                            "date":   d_str,
                            "open":   round(float(r["Open"]),  2),
                            "high":   round(float(r["High"]),  2),
                            "low":    round(float(r["Low"]),   2),
                            "close":  round(float(r["Close"]), 2),
                            "volume": vol,
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
            resp = _tpex_get(url, headers=_TWSE_HEADERS)
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
                    if int(r["Volume"]) > 0  # 成交量 0 代表當天沒開盤，不算 K 棒
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
    """掃全市場，回傳收盤價在 EMA60 上方 0~3% 內、日量 ≥ 2000 張、股價 ≥ 10 元、非金融保險的股票。"""
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
        if (last.get("close") or 0) < 10:
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


def scan_volume_breakout(limit: int = 200) -> list:
    """掃全市場，回傳今日爆量（≥近5日均量3倍）且收盤價創近20日新高、日量 ≥ 2000 張、非金融保險的股票。"""
    from app.db import get_all_db_tickers_with_meta, get_candles
    from datetime import date, timedelta

    from_date = (date.today() - timedelta(days=45)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")

    all_tickers = get_all_db_tickers_with_meta()
    results = []
    for row in all_tickers:
        ticker = row["ticker"]
        if row.get("parent_industry") == "金融保險":
            continue
        records = get_candles(ticker, from_date, to_date)
        if not records or len(records) < 21:
            continue
        last = records[-1]
        today_vol = last.get("volume") or 0
        if today_vol < 2_000_000:
            continue
        recent5 = records[-6:-1]  # 今天以外最近 5 天
        if len(recent5) < 5:
            continue
        vols5 = [r.get("volume") or 0 for r in recent5]
        avg_vol_5d = sum(vols5) / 5
        if avg_vol_5d <= 0:
            continue
        vol_ratio = today_vol / avg_vol_5d
        if vol_ratio < 3.0:
            continue
        close = last.get("close")
        closes20 = [r["close"] for r in records[-20:] if r["close"] is not None]
        if not close or not closes20 or close < max(closes20):
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
            "volume_zhang": round(today_vol / 1000),
            "vol_ratio":    round(vol_ratio, 2),
        })
        if len(results) >= limit:
            break
    return results


def fetch_institutional_trades_today() -> list[dict]:
    """抓當天全市場三大法人買賣超（上市 TWSE T86 + 上櫃 TPEx），供 daily_update.py 存 DB 用。"""
    today_str = date.today().strftime("%Y%m%d")
    today_iso = date.today().strftime("%Y-%m-%d")
    results: list[dict] = []

    # 上市（TWSE T86）
    try:
        resp = requests.get(
            "https://www.twse.com.tw/fund/T86",
            params={"response": "json", "date": today_str, "selectType": "ALLBUT0999"},
            timeout=15, headers=_TWSE_HEADERS,
        )
        data = resp.json()
        if data.get("stat") == "OK":
            for row in data.get("data", []):
                code = str(row[0]).strip()
                if not code.isdigit() or not (4 <= len(code) <= 5):
                    continue
                foreign_net = (_parse_num(row[4]) or 0) + (_parse_num(row[7]) or 0)
                trust_net   = _parse_num(row[10]) or 0
                dealer_net  = _parse_num(row[11]) or 0
                total_net   = _parse_num(row[18]) or 0
                results.append({
                    "ticker": code, "date": today_iso,
                    "foreign_net": int(foreign_net), "trust_net": int(trust_net),
                    "dealer_net": int(dealer_net), "total_net": int(total_net),
                })
        else:
            print(f"[TWSE] T86 無資料（可能非交易日）: {data.get('stat')}")
    except Exception as e:
        print(f"[TWSE] T86 三大法人失敗: {e}")

    # 上櫃（TPEx）
    try:
        resp = _tpex_get("https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading", timeout=15)
        for row in resp.json():
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            if not code.isdigit() or not (4 <= len(code) <= 5):
                continue
            foreign_net = _parse_num(row.get("ForeignInvestorsIncludeMainlandAreaInvestors-Difference")) or 0
            trust_net   = _parse_num(row.get("SecuritiesInvestmentTrustCompanies-Difference")) or 0
            dealer_net  = _parse_num(row.get("Dealers-Difference")) or 0
            total_net   = _parse_num(row.get("TotalDifference")) or 0
            results.append({
                "ticker": code, "date": today_iso,
                "foreign_net": int(foreign_net), "trust_net": int(trust_net),
                "dealer_net": int(dealer_net), "total_net": int(total_net),
            })
    except Exception as e:
        print(f"[TPEx] 三大法人失敗: {e}")

    return results


def fetch_fundamentals_today() -> list[dict]:
    """抓當天全市場本益比/殖利率/股價淨值比（上市 TWSE BWIBBU_ALL + 上櫃 TPEx），供 daily_update.py 存 DB 用。"""
    today_iso = date.today().strftime("%Y-%m-%d")
    results: list[dict] = []

    # 上市（TWSE BWIBBU_ALL）
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL",
            timeout=15, headers=_TWSE_HEADERS,
        )
        for row in resp.json():
            code = str(row.get("Code", "")).strip()
            if not code.isdigit() or not (4 <= len(code) <= 5):
                continue
            results.append({
                "ticker": code, "date": today_iso,
                "pe_ratio":       _parse_num(row.get("PEratio")),
                "dividend_yield": _parse_num(row.get("DividendYield")),
                "pb_ratio":       _parse_num(row.get("PBratio")),
            })
    except Exception as e:
        print(f"[TWSE] BWIBBU_ALL 本益比/殖利率失敗: {e}")

    # 上櫃（TPEx）
    try:
        resp = _tpex_get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis", timeout=15)
        for row in resp.json():
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            if not code.isdigit() or not (4 <= len(code) <= 5):
                continue
            results.append({
                "ticker": code, "date": today_iso,
                "pe_ratio":       _parse_num(row.get("PriceEarningRatio")),
                "dividend_yield": _parse_num(row.get("YieldRatio")),
                "pb_ratio":       _parse_num(row.get("PriceBookRatio")),
            })
    except Exception as e:
        print(f"[TPEx] 本益比/殖利率失敗: {e}")

    return results


def fetch_margin_trading_today() -> list[dict]:
    """抓當天全市場融資融券餘額（上市 TWSE MI_MARGN + 上櫃 TPEx），供 daily_update.py 存 DB 用。"""
    today_iso = date.today().strftime("%Y-%m-%d")
    results: list[dict] = []

    # 上市（TWSE MI_MARGN）
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
            timeout=15, headers=_TWSE_HEADERS,
        )
        for row in resp.json():
            code = str(row.get("股票代號", "")).strip()
            if not code.isdigit() or not (4 <= len(code) <= 5):
                continue
            results.append({
                "ticker": code, "date": today_iso,
                "margin_balance": _parse_num(row.get("融資今日餘額")),
                "margin_quota":   _parse_num(row.get("融資限額")),
                "short_balance":  _parse_num(row.get("融券今日餘額")),
                "short_quota":    _parse_num(row.get("融券限額")),
            })
    except Exception as e:
        print(f"[TWSE] MI_MARGN 融資融券失敗: {e}")

    # 上櫃（TPEx）
    try:
        resp = _tpex_get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance", timeout=15)
        for row in resp.json():
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            if not code.isdigit() or not (4 <= len(code) <= 5):
                continue
            results.append({
                "ticker": code, "date": today_iso,
                "margin_balance": _parse_num(row.get("MarginPurchaseBalance")),
                "margin_quota":   _parse_num(row.get("MarginPurchaseQuota")),
                "short_balance":  _parse_num(row.get("ShortSaleBalance")),
                "short_quota":    _parse_num(row.get("ShortSaleQuota")),
            })
    except Exception as e:
        print(f"[TPEx] 融資融券失敗: {e}")

    return results


def get_institutional_trades_history(ticker: str, days: int = 30) -> list[dict]:
    """取單一股票近 N 天的三大法人買賣超（換算成張），供個股頁顯示用。"""
    from app.db import get_institutional_trades_for_ticker
    from datetime import date, timedelta

    from_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")
    records = get_institutional_trades_for_ticker(ticker, from_date, to_date)
    return [
        {
            "date":        r["date"],
            "foreign_net": round((r.get("foreign_net") or 0) / 1000, 1),
            "trust_net":   round((r.get("trust_net") or 0) / 1000, 1),
            "dealer_net":  round((r.get("dealer_net") or 0) / 1000, 1),
            "total_net":   round((r.get("total_net") or 0) / 1000, 1),
        }
        for r in records
    ]


def _check_near_ema60_single(ticker: str) -> dict | None:
    """單一股票版「EMA60近線」判斷，邏輯同 scan_near_ema60，但只查一檔（給 AI 分析用，不用跑全市場掃描）。"""
    from app.db import get_candles
    from datetime import date, timedelta
    from_date = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")
    records = get_candles(ticker, from_date, to_date)
    if not records or len(records) < 62:
        return None
    last = records[-1]
    if (last.get("volume") or 0) < 2_000_000 or (last.get("close") or 0) < 10:
        return None
    closes = [r["close"] for r in records if r["close"] is not None]
    k, ema = 2 / 61, None
    ema_series = []
    for c in closes:
        ema = c if ema is None else c * k + ema * (1 - k)
        ema_series.append(ema)
    close = last.get("close")
    if not close or not ema:
        return None
    dev = (close - ema) / ema
    if not (0 <= dev <= 0.03):
        return None
    recent_closes = closes[-20:]
    recent_emas   = ema_series[-20:]
    if any(c < e for c, e in zip(recent_closes, recent_emas)):
        return None
    return {"ema60": round(float(ema), 2), "dev_pct": round(dev * 100, 2)}


def _check_volume_breakout_single(ticker: str) -> dict | None:
    """單一股票版「量價突破」判斷，邏輯同 scan_volume_breakout，但只查一檔。"""
    from app.db import get_candles
    from datetime import date, timedelta
    from_date = (date.today() - timedelta(days=45)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")
    records = get_candles(ticker, from_date, to_date)
    if not records or len(records) < 21:
        return None
    last = records[-1]
    today_vol = last.get("volume") or 0
    if today_vol < 2_000_000:
        return None
    recent5 = records[-6:-1]
    if len(recent5) < 5:
        return None
    avg_vol_5d = sum(r.get("volume") or 0 for r in recent5) / 5
    if avg_vol_5d <= 0:
        return None
    vol_ratio = today_vol / avg_vol_5d
    if vol_ratio < 3.0:
        return None
    close = last.get("close")
    closes20 = [r["close"] for r in records[-20:] if r["close"] is not None]
    if not close or not closes20 or close < max(closes20):
        return None
    return {"vol_ratio": round(vol_ratio, 2)}


def get_stock_signals(ticker: str, info: dict) -> dict:
    """彙整這支股票目前的三大法人狀況、是否命中技術面掃描訊號、三關價，供 AI 分析用。
    刻意不直接呼叫全市場掃描函式（scan_near_ema60 等），避免每次分析都跑一次全市場逐檔掃描拖慢速度。"""
    inst_trades = get_institutional_trades_history(ticker, 30)
    streak, streak_total = 0, 0
    for r in reversed(inst_trades):
        net = (r.get("foreign_net") or 0) + (r.get("trust_net") or 0)
        if net <= 0:
            break
        streak += 1
        streak_total += net

    hits = []
    try:
        if _detect_ma_pattern(ticker).get("bird_beak"):
            hits.append("鳥嘴與分歧（先發散再收斂）")
    except Exception:
        pass
    ema_hit = _check_near_ema60_single(ticker)
    if ema_hit:
        hits.append(f"EMA60近線（偏離 EMA60 {ema_hit['dev_pct']}%）")
    vol_hit = _check_volume_breakout_single(ticker)
    if vol_hit:
        hits.append(f"量價突破（今日量能為近5日均量的 {vol_hit['vol_ratio']} 倍，且創20日收盤新高）")
    if streak >= 3:
        hits.append(f"法人連買（外資+投信連續 {streak} 天合計買超 {round(streak_total)} 張）")

    gates = None
    prev_high, prev_low = info.get("prev_high"), info.get("prev_low")
    if prev_high is not None and prev_low is not None:
        rng = prev_high - prev_low
        gates = {
            "upper": round(prev_high + rng * 0.382, 2),
            "mid":   round((prev_high + prev_low) / 2, 2),
            "lower": round(prev_low - rng * 0.382, 2),
        }

    return {
        "institutional_streak_days":       streak,
        "institutional_streak_total_zhang": round(streak_total),
        "institutional_recent":            inst_trades[-5:],
        "scan_hits":                       hits,
        "gates":                           gates,
    }


def scan_institutional_buying(min_days: int = 3, limit: int = 200, min_total_net_zhang: int = 0) -> list:
    """掃全市場，回傳外資+投信合計連續買超 ≥ min_days 個交易日，且合計買超 ≥ min_total_net_zhang 張的股票。"""
    from app.db import get_all_db_tickers_with_meta, get_all_institutional_trades_in_range, get_candles
    from datetime import date, timedelta

    lookback_days = min_days + 15  # 留緩衝扣掉假日
    from_date = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")

    trades_map = get_all_institutional_trades_in_range(from_date, to_date)
    meta_map   = {row["ticker"]: row for row in get_all_db_tickers_with_meta()}

    candle_from = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")

    results = []
    for ticker, records in trades_map.items():
        meta = meta_map.get(ticker)
        if not meta or meta.get("parent_industry") == "金融保險":
            continue
        records = sorted(records, key=lambda r: r["date"])
        streak, total_net = 0, 0
        for r in reversed(records):
            net = (r.get("foreign_net") or 0) + (r.get("trust_net") or 0)
            if net <= 0:
                break
            streak += 1
            total_net += net
        if streak < min_days:
            continue

        candles = get_candles(ticker, candle_from, to_date)
        if not candles:
            continue
        last  = candles[-1]
        close = last.get("close")
        prev  = candles[-2] if len(candles) >= 2 else last
        prev_close = prev.get("close")
        change_pct = round((close - prev_close) / prev_close * 100, 2) if close and prev_close else None

        results.append({
            "ticker":          ticker,
            "name":            meta.get("name") or "",
            "exchange":        meta.get("exchange") or "",
            "close":           round(float(close), 2) if close else None,
            "change_pct":      change_pct,
            "streak_days":     streak,
            "total_net_zhang": round(total_net / 1000),
        })

    if min_total_net_zhang:
        results = [r for r in results if r["total_net_zhang"] >= min_total_net_zhang]

    # 優先看買超規模（張數），連續天數只當篩選門檻（已 >= min_days），不當主要排序依據，
    # 避免「連續天數多但每天量極小」的雜訊排到「量大但天數略少」的前面
    results.sort(key=lambda x: (x["total_net_zhang"], x["streak_days"]), reverse=True)
    return results[:limit]


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


def _get_info_from_db(ticker: str, fundamentals_map: dict | None = None) -> dict | None:
    """從 DB candles + meta 取得基本資訊，不打外部 API。
    price/volume 用最後一筆收盤，capital 用 _tw_stock_capital。
    fundamentals_map：screen_stocks 全市場掃描時預先撈好的 {ticker: {pe_ratio, dividend_yield, pb_ratio}}，
    避免 2000 檔迴圈內各查一次 DB。
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
    fund = (fundamentals_map or {}).get(ticker, {})
    return {
        "ticker":      ticker,
        "name":        name,
        "price":       round(float(price), 2),
        "change_pct":  change_pct,
        "volume_zhang": volume_zhang,
        "capital_yi":  capital_yi,
        "exchange":    exchange,
        "pe_ratio":       fund.get("pe_ratio"),
        "dividend_yield": fund.get("dividend_yield"),
        "pb_ratio":       fund.get("pb_ratio"),
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
    fundamentals_map = {}
    if use_db:
        meta_list    = get_all_db_tickers_with_meta()
        tickers      = [m["ticker"] for m in meta_list]
        meta_name_db = {m["ticker"]: m.get("name") for m in meta_list if m.get("name")}
        from app.db import get_all_latest_fundamentals
        fundamentals_map = get_all_latest_fundamentals()

    results = []
    for ticker in tickers:
        try:
            info = _get_info_from_db(ticker, fundamentals_map) if use_db else get_stock_info(ticker)
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


def get_watchlist_quotes(tickers: list[str]) -> list[dict]:
    """取得自選股清單的即時基本資料（股名、成交價、漲跌、委買委賣等），供看盤頁自選分頁使用。"""
    _load_tw_stock_names()
    merged_names: dict[str, str] = {**COMMON_STOCK_NAMES, **ETF_NAMES}
    merged_names.update(_tw_stock_names)
    stocks = [{"ticker": t, "name": merged_names.get(t, t)} for t in tickers]

    client = _get_fugle()
    if not client or not stocks:
        return stocks

    def _fetch(ticker: str):
        try:
            resp = client.stock.intraday.quote(symbol=ticker)
            data = resp.get("data", resp) if isinstance(resp, dict) else {}
            if not isinstance(data, dict):
                return ticker, {}

            close = data.get("closePrice") or data.get("lastPrice")
            ref   = data.get("referencePrice")
            change = change_pct = None
            if close and ref:
                change     = round(float(close) - float(ref), 2)
                change_pct = round(change / float(ref) * 100, 2)

            bids = data.get("bids") or []
            asks = data.get("asks") or []
            total = data.get("total") or {}
            last_size = data.get("lastSize")
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
                "close":              round(float(close), 2) if close else None,
                "change":             change,
                "change_pct":         change_pct,
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
        quote_map = dict(pool.map(_fetch, tickers))

    return [{**s, **quote_map.get(s["ticker"], {})} for s in stocks]


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
            resp = _tpex_get(
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
        resp = _tpex_get(
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


def get_movers_ranking(direction: str = "up", limit: int = 50, force: bool = False) -> list:
    """漲跌幅排行（合併上市 + 上櫃），direction: "up" 漲幅榜 / "down" 跌幅榜。
    直接用 Fugle snapshot/movers，該端點本身就是照漲跌幅排序好的，不用像成交值/週轉率
    那樣自己抓全市場再排序。
    """
    cache_key = f"movers_{direction}"
    if not force:
        cached = _cache_get(_ranking_cache, cache_key, RANKING_TTL)
        if cached is not None:
            return cached[:limit]

    client = _get_fugle()
    results = []
    if client:
        for market in ("TSE", "OTC"):
            try:
                resp = client.stock.snapshot.movers(
                    market=market, direction=direction, change="percent", type="ALLBUT0999"
                )
                data = resp.get("data", []) if isinstance(resp, dict) else []
                label = "上市" if market == "TSE" else "上櫃"
                for item in data:
                    close   = item.get("closePrice")
                    chg     = item.get("change")
                    chg_pct = item.get("changePercent")
                    vol     = item.get("tradeVolume", 0) or 0
                    tv      = item.get("tradeValue", 0) or 0
                    results.append({
                        "ticker":             item.get("symbol", ""),
                        "name":               item.get("name", ""),
                        "close":              round(float(close), 2) if close is not None else None,
                        "change":             round(float(chg), 2) if chg is not None else None,
                        "change_pct":         round(float(chg_pct), 2) if chg_pct is not None else None,
                        "trade_value_yi":     round(float(tv) / 1e8, 2) if tv else None,
                        "trade_volume_zhang": round(int(vol) / 1000) if vol else None,
                        "exchange":           label,
                    })
            except Exception as e:
                print(f"[Fugle] snapshot movers {market} {direction} 失敗: {e}")

    results = [r for r in results if r.get("change_pct") is not None]
    results.sort(key=lambda x: x["change_pct"], reverse=(direction == "up"))
    results = _enrich_with_intraday(results[:limit])

    _cache_set(_ranking_cache, cache_key, results)
    return results[:limit]


def get_industry_performance(force: bool = False) -> list:
    """依 TWSE 產業大分類（parent_industry）計算今日各產業平均漲跌幅與成交值，
    用 Fugle snapshot/quotes 全市場即時報價（盤中即時），找出當天熱門產業。
    """
    if not force:
        cached = _cache_get(_ranking_cache, "industry_performance", RANKING_TTL)
        if cached is not None:
            return cached

    client = _get_fugle()
    if not client:
        return []

    quotes: dict[str, dict] = {}
    for market in ("TSE", "OTC"):
        try:
            resp = client.stock.snapshot.quotes(market=market)
            for item in (resp.get("data", []) if isinstance(resp, dict) else []):
                symbol  = item.get("symbol", "")
                chg_pct = item.get("changePercent")
                tv      = item.get("tradeValue")
                if symbol and chg_pct is not None:
                    quotes[symbol] = {"change_pct": float(chg_pct), "trade_value": float(tv or 0)}
        except Exception as e:
            print(f"[Fugle] snapshot quotes {market} 失敗: {e}")

    if not quotes:
        return []

    from app.db import get_all_db_tickers_with_meta
    groups: dict[str, list] = {}
    for row in get_all_db_tickers_with_meta():
        industry = row.get("parent_industry")
        # 排除未分類到中文名稱、還是原始數字代碼的產業（TWSE_INDUSTRY_CODE_MAP 沒收錄）
        if not industry or industry.isdigit():
            continue
        q = quotes.get(row["ticker"])
        if q:
            groups.setdefault(industry, []).append(q)

    results = []
    for industry, items in groups.items():
        avg_chg  = sum(i["change_pct"] for i in items) / len(items)
        total_tv = sum(i["trade_value"] for i in items)
        results.append({
            "industry":        industry,
            "avg_change_pct":  round(avg_chg, 2),
            "trade_value_yi":  round(total_tv / 1e8, 2),
            "stock_count":     len(items),
        })

    results.sort(key=lambda x: x["avg_change_pct"], reverse=True)
    _cache_set(_ranking_cache, "industry_performance", results)
    return results


def get_upcoming_dividends(days: int = 60, force: bool = False) -> list:
    """近 N 天全市場即將除權息清單。Fugle corporate-actions/dividends 這個端點不管傳哪個
    symbol，實際上都會回傳全市場資料（已驗證），所以只需要打一次 API，不用逐股查。
    注意：這個端點的 start_date 參數實測也不會真的過濾（會夾帶範圍外的舊資料），
    所以日期範圍要自己在這裡過濾，不能信任 API 回傳的內容都在請求範圍內。
    """
    cache_key = f"upcoming_dividends_{days}"
    if not force:
        cached = _cache_get(_ranking_cache, cache_key, RANKING_TTL)
        if cached is not None:
            return cached

    client = _get_fugle()
    if not client:
        return []

    results = []
    try:
        today_str  = date.today().strftime("%Y-%m-%d")
        future_str = (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")
        # symbol 參數必填但不影響回傳內容，隨便帶一個常見代號即可
        resp = client.stock.corporate_actions.dividends(
            symbol="2330", start_date=today_str, end_date=future_str
        )
        data = resp.get("data", resp) if isinstance(resp, dict) else []
        if not isinstance(data, list):
            data = []
        for row in data:
            symbol = row.get("symbol")
            name   = row.get("name")
            ex_date = row.get("date")
            if not symbol or not name or not ex_date:
                continue
            # API 的 start_date/end_date 過濾不可靠，自己再過濾一次
            if not (today_str <= ex_date <= future_str):
                continue
            results.append({
                "ticker":        symbol,
                "name":          name,
                "date":          ex_date,
                "dividend_type": row.get("dividendType"),
                "cash_dividend": row.get("cashDividend"),
                "stock_dividend_shares": row.get("stockDividendShares"),
            })
    except Exception as e:
        print(f"[Fugle] corporate-actions dividends 失敗: {e}")

    results.sort(key=lambda x: (x["date"], x["ticker"]))
    _cache_set(_ranking_cache, cache_key, results)
    return results


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


def get_intraday_chart(ticker: str) -> list:
    """取得當日分時走勢（每分鐘K棒），供前端畫分時線圖用。收盤後仍可查當天資料，隔天即作廢，不存 DB。"""
    client = _get_fugle()
    if not client:
        return []
    try:
        resp = client.stock.intraday.candles(symbol=ticker, timeframe="1")
        data = resp.get("data", []) if isinstance(resp, dict) else []
        result = []
        for c in (data if isinstance(data, list) else []):
            dt = datetime.fromisoformat(c["date"])
            result.append({
                "time":    dt.strftime("%H:%M"),
                "price":   c.get("close"),
                "average": c.get("average"),
                "volume":  c.get("volume", 0),
            })
        return result
    except Exception as e:
        print(f"[Fugle] intraday candles {ticker} 失敗: {e}")
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


# ── WebSocket 即時訂閱管理（比照 futures_data.py 的 futopt 模式）──────────
import asyncio
import json as _json

_ws_queues: dict[str, set] = {}   # symbol → set of asyncio.Queue（每個連線一個 queue）
_ws_lock = threading.Lock()
_ws_stock = None   # Fubon WS stock client（全域共用，訂閱 trades + books）


def _reset_ws_stock():
    """Fubon WS 斷線時重置，讓下次呼叫重新建立連線。"""
    global _ws_stock
    with _fugle_lock:
        _ws_stock = None
    print("[Fubon WS] 股票連線已重置，等待下次請求重新建立")


def _get_ws_stock():
    """取得 Fubon WebSocket stock client，確保已登入並連線（沿用 _get_fugle 的同一組登入）。"""
    global _ws_stock
    if _ws_stock is not None:
        return _ws_stock
    with _fugle_lock:
        if _ws_stock is not None:
            return _ws_stock
        _get_fugle()   # 確保 _fugle_sdk 已初始化
        if not _fugle_sdk:
            raise RuntimeError("Fugle SDK 未就緒，無法建立股票 WebSocket 連線")
        stock = _fugle_sdk.marketdata.websocket_client.stock

        def _on_message(raw):
            try:
                msg = _json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                msg = raw
            if not isinstance(msg, dict) or msg.get("event") != "data":
                return
            payload = dict(msg.get("data") or {})
            sym = payload.get("symbol", "")
            payload["channel"] = msg.get("channel", "")
            with _ws_lock:
                queues = _ws_queues.get(sym, set()).copy()
            for q in queues:
                try:
                    loop = q._loop
                    asyncio.run_coroutine_threadsafe(q.put(payload), loop)
                except Exception:
                    pass

        def _on_disconnect(msg=None):
            print(f"[Fubon WS] 股票連線斷線: {msg}")
            _reset_ws_stock()

        stock.on("message", _on_message)
        for evt in ("disconnect", "error", "close"):
            try:
                stock.on(evt, _on_disconnect)
            except Exception:
                pass
        stock.connect()
        time.sleep(2)   # 等連線建立後再 return（connect() 是非同步啟動）
        _ws_stock = stock
        print("[Fubon WS] 股票連線已建立")
    return _ws_stock


def add_ws_listener(symbol: str, queue: "asyncio.Queue") -> None:
    """前端 WebSocket 連線進來時，把 queue 登記到 symbol 訂閱（trades + books）。"""
    stock = _get_ws_stock()
    with _ws_lock:
        if symbol not in _ws_queues:
            _ws_queues[symbol] = set()
            for attempt in range(2):
                try:
                    stock.subscribe({"channel": "trades", "symbol": symbol})
                    stock.subscribe({"channel": "books",  "symbol": symbol})
                    print(f"[Fubon WS] 訂閱股票 {symbol} 成功")
                    break
                except Exception as e:
                    print(f"[Fubon WS] subscribe {symbol} attempt {attempt+1} failed: {e}")
                    if attempt == 0:
                        time.sleep(0.5)
        _ws_queues[symbol].add(queue)


def remove_ws_listener(symbol: str, queue: "asyncio.Queue") -> None:
    """前端斷線時移除 queue；該股票沒人訂閱時順便取消訂閱，避免訂閱數持續累積。"""
    with _ws_lock:
        listeners = _ws_queues.get(symbol)
        if not listeners:
            return
        listeners.discard(queue)
        if listeners:
            return
        del _ws_queues[symbol]
        stock = _ws_stock
    if stock is not None:
        try:
            stock.unsubscribe({"channel": "trades", "symbol": symbol})
            stock.unsubscribe({"channel": "books",  "symbol": symbol})
        except Exception as e:
            print(f"[Fubon WS] unsubscribe {symbol} 失敗（略過）: {e}")
