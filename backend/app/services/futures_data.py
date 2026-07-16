import os
import threading
import calendar
import time
from datetime import date, datetime, timezone, timedelta

TZ_TAIPEI = timezone(timedelta(hours=8))
import requests

_sdk         = None
_rest_client = None
_lock        = threading.Lock()

MONTH_CODES = "ABCDEFGHIJKL"

_symbol_cache: dict[str, tuple[float, str]] = {}   # product → (查詢時間, symbol)
_SYMBOL_CACHE_TTL = 3600  # 近月合約一天最多換一次，1 小時內重複查詢直接用快取


def _in_day_session(epoch: int) -> bool:
    """判斷某個 unix timestamp 是否落在台指期日盤時段（08:45–13:45）。"""
    dt = datetime.fromtimestamp(epoch, tz=TZ_TAIPEI)
    mins = dt.hour * 60 + dt.minute
    return 8 * 60 + 45 <= mins <= 13 * 60 + 45


def _in_night_session(epoch: int) -> bool:
    """判斷某個 unix timestamp 是否落在台指期夜盤時段（15:00–隔日05:00）。"""
    dt = datetime.fromtimestamp(epoch, tz=TZ_TAIPEI)
    mins = dt.hour * 60 + dt.minute
    return mins >= 15 * 60 or mins < 5 * 60


def _current_symbol_fallback(product: str = "TXF") -> str:
    """日期推算備援：台指期結算日固定是每月第三個星期三（未考慮國定假日順延）。"""
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


def _current_symbol(product: str = "TXF") -> str:
    """向 Fugle 查詢該商品目前上市的合約，取結算日最近且尚未結算的作為近月合約。
    比自己用「每月第三個星期三」推算更可靠（會遇到國定假日順延結算日的情況），
    查詢失敗時退回日期推算。"""
    cached = _symbol_cache.get(product)
    if cached and time.time() - cached[0] < _SYMBOL_CACHE_TTL:
        return cached[1]
    try:
        data = _get_client().futopt.intraday.tickers(type="FUTURE", product=product)
        contracts = data.get("data", [])
        today_str = date.today().strftime("%Y-%m-%d")
        upcoming = sorted(
            (c for c in contracts if c.get("settlementDate") and c.get("symbol") and c["settlementDate"] >= today_str),
            key=lambda c: c["settlementDate"],
        )
        if upcoming:
            symbol = upcoming[0]["symbol"]
            _symbol_cache[product] = (time.time(), symbol)
            return symbol
    except Exception as e:
        print(f"[futures] 取得 {product} 合約清單失敗，改用日期推算: {e}")
    return _current_symbol_fallback(product)


def _init_sdk():
    global _sdk, _rest_client
    from fubon_neo.sdk import FubonSDK, Mode
    sdk = FubonSDK()
    sdk.login(
        os.environ["FUBON_ID"],
        os.environ["FUBON_PASSWORD"],
        os.environ["FUBON_CERT_PATH"],
        os.environ["FUBON_CERT_PASSWORD"],
    )
    sdk.init_realtime(Mode.Normal)
    _sdk         = sdk
    _rest_client = sdk.marketdata.rest_client


def _get_client():
    global _rest_client
    if _rest_client is None:
        with _lock:
            if _rest_client is None:
                _init_sdk()
    return _rest_client


def get_futures_quote(symbol: str | None = None, session: str = "regular") -> dict:
    symbol = symbol or _current_symbol()
    kwargs = {"symbol": symbol}
    if session == "afterhours":
        kwargs["session"] = "afterhours"
    data   = _get_client().futopt.intraday.quote(**kwargs)
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


def get_futures_candles(symbol: str | None = None, timeframe: str = "60", session: str = "regular") -> list:
    symbol = symbol or _current_symbol()

    if timeframe == "D":
        import yfinance as yf
        # 用加權指數（^TWII）做日K，走勢與台指期高度一致
        hist = yf.Ticker("^TWII").history(period="6mo", interval="1d")
        if hist.empty:
            return []
        if hist.index.tz is not None:
            hist.index = hist.index.tz_convert("Asia/Taipei")
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

    from app.db import get_futures_candles_db
    product = symbol[:3]  # "TXF" or "MTX"

    # 今日盤中即時資料
    today_candles = []
    kwargs = {"symbol": symbol, "timeframe": timeframe}
    if session == "afterhours":
        kwargs["session"] = "afterhours"
    try:
        data = _get_client().futopt.intraday.candles(**kwargs)
        for c in data.get("data", []):
            dt = datetime.fromisoformat(c["date"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ_TAIPEI)
            today_candles.append({
                "time":   int(dt.timestamp()),
                "open":   c["open"],
                "high":   c["high"],
                "low":    c["low"],
                "close":  c["close"],
                "volume": c.get("volume", 0),
            })
    except Exception as e:
        print(f"[futures] intraday.candles 失敗: {e}")

    # DB 歷史資料：日盤／夜盤共用同一個 (product, timeframe) 存放（時間本來就不重疊，
    # 天然接續成連續走勢），這裡依目前分頁只挑對應時段的歷史，避免兩邊混在一起顯示
    hist = get_futures_candles_db(product, timeframe)
    session_filter = _in_night_session if session == "afterhours" else _in_day_session
    hist = [c for c in hist if session_filter(c["time"])]
    if today_candles:
        today_min_time = min(c["time"] for c in today_candles)
        hist = [c for c in hist if c["time"] < today_min_time]

    return hist + today_candles


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

# ── WebSocket 即時訂閱管理 ───────────────────────────────
import asyncio
import json as _json

# symbol → set of asyncio.Queue（每個連線一個 queue）
_ws_queues: dict[str, set] = {}
_ws_lock = threading.Lock()
_ws_futopt = None   # Fubon WS futopt client（全域共用）


def _reset_ws_futopt():
    """Fubon WS 斷線時重置，讓下次呼叫重新建立連線。"""
    global _ws_futopt
    with _lock:
        _ws_futopt = None
    print("[Fubon WS] 連線已重置，等待下次請求重新建立")


def _get_ws_futopt():
    """取得 Fubon WebSocket futopt client，確保已登入並連線。"""
    global _ws_futopt
    if _ws_futopt is not None:
        return _ws_futopt
    with _lock:
        if _ws_futopt is not None:
            return _ws_futopt
        _get_client()   # 確保 _sdk 已初始化（Mode.Normal）
        futopt = _sdk.marketdata.websocket_client.futopt

        def _on_message(raw):
            try:
                msg = _json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                msg = raw
            if not isinstance(msg, dict):
                return
            event = msg.get("event")
            # 處理即時成交（data）和首次快照（snapshot 裡含 trades）
            if event == "data":
                payload = msg.get("data") or {}
                sym = payload.get("symbol", "")
            elif event == "snapshot":
                payload = msg.get("data") or {}
                # 只有帶 trades 的快照才轉發（報價快照），candles 快照略過
                if not payload.get("trades"):
                    return
                sym = payload.get("symbol", "")
            else:
                return
            with _ws_lock:
                queues = _ws_queues.get(sym, set()).copy()
            for q in queues:
                try:
                    loop = q._loop
                    asyncio.run_coroutine_threadsafe(q.put(payload), loop)
                except Exception:
                    pass

        def _on_disconnect(msg=None):
            print(f"[Fubon WS] 斷線: {msg}")
            _reset_ws_futopt()

        futopt.on("message", _on_message)
        # 有些版本提供 disconnect / error / close 事件
        for evt in ("disconnect", "error", "close"):
            try:
                futopt.on(evt, _on_disconnect)
            except Exception:
                pass
        futopt.connect()
        time.sleep(2)   # 等連線建立後再 return（connect() 是非同步啟動）
        _ws_futopt = futopt
        print("[Fubon WS] 連線已建立")
    return _ws_futopt


def add_ws_listener(symbol: str, queue: asyncio.Queue):
    """前端 WebSocket 連線進來時，把 queue 登記到 symbol 訂閱。"""
    futopt = _get_ws_futopt()
    with _ws_lock:
        if symbol not in _ws_queues:
            _ws_queues[symbol] = set()
            # 訂閱兩個 channel；已連線時通常第一次就成功
            for attempt in range(2):
                try:
                    futopt.subscribe({"channel": "trades", "symbol": symbol})
                    futopt.subscribe({"channel": "quote",  "symbol": symbol})
                    print(f"[Fubon WS] 訂閱 {symbol} 成功")
                    break
                except Exception as e:
                    print(f"[Fubon WS] subscribe {symbol} attempt {attempt+1} failed: {e}")
                    if attempt == 0:
                        time.sleep(0.5)
        _ws_queues[symbol].add(queue)


def remove_ws_listener(symbol: str, queue: asyncio.Queue):
    """前端斷線時移除 queue。"""
    with _ws_lock:
        _ws_queues.get(symbol, set()).discard(queue)
