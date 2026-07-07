import os
import threading
import calendar
import time
from datetime import date, datetime
import requests

_sdk         = None
_rest_client = None
_lock        = threading.Lock()

MONTH_CODES = "ABCDEFGHIJKL"


def _current_symbol(product: str = "TXF") -> str:
    """自動產生當前近月合約代號，product 可為 TXF 或 MTX。"""
    today = date.today()
    year, month = today.year, today.month
    cal       = calendar.monthcalendar(year, month)
    weds      = [w[2] for w in cal if w[2] != 0]
    third_wed = weds[2] if len(weds) >= 3 else weds[-1]
    if today > date(year, month, third_wed):
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return f"{product}{MONTH_CODES[month - 1]}{year % 10}"


def _init_sdk():
    global _sdk, _rest_client
    from fubon_neo.sdk import FubonSDK
    sdk = FubonSDK()
    sdk.login(
        os.environ["FUBON_ID"],
        os.environ["FUBON_PASSWORD"],
        os.environ["FUBON_CERT_PATH"],
        os.environ["FUBON_CERT_PASSWORD"],
    )
    sdk.init_realtime()
    _sdk         = sdk
    _rest_client = sdk.marketdata.rest_client


def _get_client():
    global _rest_client
    if _rest_client is None:
        with _lock:
            if _rest_client is None:
                _init_sdk()
    return _rest_client


def get_futures_quote(symbol: str | None = None) -> dict:
    symbol = symbol or _current_symbol()
    data   = _get_client().futopt.intraday.quote(symbol=symbol)
    price  = data.get("closePrice") or (data.get("lastTrade") or {}).get("price")
    prev   = data.get("previousClose")
    change = round(price - prev, 0) if price and prev else None
    chg_pct = round(change / prev * 100, 2) if change and prev else None
    return {
        "symbol":     symbol,
        "name":       data.get("name", "台股期貨"),
        "price":      price,
        "prev_close": prev,
        "open":       data.get("openPrice"),
        "high":       data.get("highPrice"),
        "low":        data.get("lowPrice"),
        "volume":     (data.get("total") or {}).get("tradeVolume"),
        "change":     change,
        "change_pct": chg_pct,
    }


def get_futures_candles(symbol: str | None = None, timeframe: str = "60") -> list:
    symbol = symbol or _current_symbol()

    if timeframe == "D":
        import yfinance as yf
        hist = yf.Ticker("TXF=F").history(period="6mo", interval="1d")
        if hist.empty:
            return []
        result = []
        for ts, row in hist.iterrows():
            result.append({
                "date":   ts.strftime("%Y-%m-%d"),
                "open":   round(float(row["Open"])),
                "high":   round(float(row["High"])),
                "low":    round(float(row["Low"])),
                "close":  round(float(row["Close"])),
                "volume": int(row["Volume"]),
            })
        return result

    data   = _get_client().futopt.intraday.candles(symbol=symbol, timeframe=timeframe)
    result = []
    for c in data.get("data", []):
        dt = datetime.fromisoformat(c["date"])
        result.append({
            "time":   int(dt.timestamp()),
            "open":   c["open"],
            "high":   c["high"],
            "low":    c["low"],
            "close":  c["close"],
            "volume": c.get("volume", 0),
        })
    return result


def get_institutional_positions() -> list:
    """TAIFEX openapi 三大法人台指期未沖銷部位（近 30 天）"""
    try:
        resp = requests.get(
            "https://openapi.taifex.com.tw/v1/FutContractsDate",
            timeout=10,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        print(f"[TAIFEX] 法人資料失敗: {e}")
        return []

    # 只取 TX（台指期），整理成前端易用格式
    result: dict[str, dict] = {}
    for r in rows:
        if r.get("ContractCode") != "TX" and r.get("商品代號") != "TX":
            code = r.get("ContractCode") or r.get("商品代號") or ""
            if "TX" not in code:
                continue
        d    = r.get("Date") or r.get("日期", "")
        role = r.get("IdentityType") or r.get("身份別", "")
        if not d or not role:
            continue
        if d not in result:
            result[d] = {"date": d}
        net = 0
        try:
            net = int(r.get("NetOpenInterestVolume") or r.get("多空淨額未沖銷口數", 0))
        except Exception:
            pass
        role_map = {
            "Dealers":             "dealer",
            "Investment Trust":    "trust",
            "Foreign Investors":   "foreign",
            "自營商": "dealer", "投信": "trust", "外資": "foreign",
        }
        key = role_map.get(role)
        if key:
            result[d][key] = net

    return sorted(result.values(), key=lambda x: x["date"])[-30:]
