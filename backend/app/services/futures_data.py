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


def _is_night_session_now() -> bool:
    """判斷現在是否為台指期夜盤交易時段（15:00–隔日05:00），決定即時報價要查日盤還夜盤。"""
    now = datetime.now(tz=TZ_TAIPEI)
    day  = now.weekday()   # 0=一 ... 6=日
    mins = now.hour * 60 + now.minute
    if 0 <= day <= 4 and mins >= 15 * 60:   # 週一到週五 15:00 之後
        return True
    if 1 <= day <= 5 and mins < 5 * 60:     # 週二到週六 05:00 前（延續前一晚）
        return True
    return False


def _next_trading_date(d: date) -> date:
    """往後找下一個交易日（跳過週六日）。"""
    d += timedelta(days=1)
    while d.weekday() >= 5:   # 5=六, 6=日
        d += timedelta(days=1)
    return d


def _trading_day_of(epoch: int) -> str:
    """依台指期「交易日」定義（前一天15:00夜盤起算～當天13:45日盤收盤算同一個交易日）
    判斷某個 unix timestamp 屬於哪個交易日，回傳日期字串。"""
    dt   = datetime.fromtimestamp(epoch, tz=TZ_TAIPEI)
    mins = dt.hour * 60 + dt.minute
    d    = dt.date()
    if mins >= 15 * 60:
        # 15:00 之後開始的夜盤，算下一個交易日
        return _next_trading_date(d).strftime("%Y-%m-%d")
    if d.weekday() >= 5:
        # 週六/週日凌晨（週五夜盤延續到週六05:00），算下一個交易日（週一）
        return _next_trading_date(d - timedelta(days=1)).strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d")


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


def get_futures_quote(symbol: str | None = None) -> dict:
    """即時報價：日夜盤不分開顯示，自動依現在時間查目前實際在交易的那一段。"""
    symbol = symbol or _current_symbol()
    kwargs = {"symbol": symbol}
    if _is_night_session_now():
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


def get_futures_candles(symbol: str | None = None, timeframe: str = "60") -> list:
    """K 線：日盤＋夜盤接續成一條連續走勢，不分開查。"""
    symbol = symbol or _current_symbol()

    if timeframe == "D":
        import yfinance as yf
        from app.db import get_futures_candles_db

        # 底：加權指數（^TWII）近6個月日K，涵蓋還沒累積到期貨自己資料的較早期間
        result: dict[str, dict] = {}
        hist = yf.Ticker("^TWII").history(period="6mo", interval="1d")
        if not hist.empty:
            if hist.index.tz is not None:
                hist.index = hist.index.tz_convert("Asia/Taipei")
            for ts, row in hist.iterrows():
                d = ts.strftime("%Y-%m-%d")
                result[d] = {
                    "date":   d,
                    "open":   round(float(row["Open"])),
                    "high":   round(float(row["High"])),
                    "low":    round(float(row["Low"])),
                    "close":  round(float(row["Close"])),
                    "volume": int(row["Volume"]),
                }

        # 蓋：把有累積到日盤+夜盤的交易日換成真正的期貨資料（含夜盤價格波動，
        # 指數只涵蓋現貨盤中 09:00–13:30，看不到夜盤的漲跌），依台指期交易日定義分組
        # （用 {day: {time: candle}} 依時間去重，避免 DB 跟即時資料重疊時重複計入成交量）
        product = symbol[:3]
        grouped: dict[str, dict[int, dict]] = {}
        for c in get_futures_candles_db(product, "60"):
            grouped.setdefault(_trading_day_of(c["time"]), {})[c["time"]] = c

        # 加：當下正在進行、還沒被排程存進 DB 的今日盤中資料（讓還在走的交易日也能即時反映）
        for kwargs in ({"symbol": symbol, "timeframe": "60"},
                        {"symbol": symbol, "timeframe": "60", "session": "afterhours"}):
            try:
                data = _get_client().futopt.intraday.candles(**kwargs)
                for c in data.get("data", []):
                    dt = datetime.fromisoformat(c["date"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=TZ_TAIPEI)
                    t = int(dt.timestamp())
                    grouped.setdefault(_trading_day_of(t), {})[t] = {
                        "time": t, "open": c["open"], "high": c["high"],
                        "low": c["low"], "close": c["close"], "volume": c.get("volume", 0),
                    }
            except Exception as e:
                print(f"[futures] 日K 即時資料失敗: {e}")
        for d, candle_map in grouped.items():
            candles = sorted(candle_map.values(), key=lambda c: c["time"])
            result[d] = {
                "date":   d,
                "open":   candles[0]["open"],
                "high":   max(c["high"] for c in candles),
                "low":    min(c["low"] for c in candles),
                "close":  candles[-1]["close"],
                "volume": sum(c.get("volume", 0) for c in candles),
            }

        return sorted(result.values(), key=lambda r: r["date"])

    from app.db import get_futures_candles_db
    product = symbol[:3]  # "TXF" or "MTX"

    # 今日盤中即時資料：日盤＋夜盤都查，依時間排序合併（兩者時段本來就不重疊）
    today_candles = {}
    for kwargs in ({"symbol": symbol, "timeframe": timeframe},
                    {"symbol": symbol, "timeframe": timeframe, "session": "afterhours"}):
        try:
            data = _get_client().futopt.intraday.candles(**kwargs)
            for c in data.get("data", []):
                dt = datetime.fromisoformat(c["date"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TZ_TAIPEI)
                t = int(dt.timestamp())
                today_candles[t] = {
                    "time":   t,
                    "open":   c["open"],
                    "high":   c["high"],
                    "low":    c["low"],
                    "close":  c["close"],
                    "volume": c.get("volume", 0),
                }
        except Exception as e:
            print(f"[futures] intraday.candles 失敗: {e}")
    today_candles = sorted(today_candles.values(), key=lambda c: c["time"])

    # DB 歷史資料：日盤／夜盤共用同一個 (product, timeframe) 存放，時間本來就不重疊，
    # 直接接續成一條連續走勢
    hist = get_futures_candles_db(product, timeframe)
    if today_candles:
        today_min_time = today_candles[0]["time"]
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
