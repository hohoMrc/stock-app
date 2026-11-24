import os
import threading
import calendar
import time
from datetime import date, datetime, timezone, timedelta

TZ_TAIPEI = timezone(timedelta(hours=8))
import requests

_sdk         = None
_rest_client = None
_lock        = threading.RLock()   # 可重入：_get_ws_futopt 持鎖時會再呼叫 _get_client()

MONTH_CODES = "ABCDEFGHIJKL"

_symbol_cache: dict[str, tuple[float, str]] = {}   # product → (查詢時間, symbol)
_SYMBOL_CACHE_TTL = 3600  # 近月合約一天最多換一次，1 小時內重複查詢直接用快取


def _is_night_session_now() -> bool:
    """決定即時報價要查日盤還夜盤：查「最近一段有在交易」的盤別。
    只有平日 08:45–15:00（日盤進行中、或剛收盤還沒進夜盤）查日盤，其餘都查夜盤——
    包含夜盤 05:00 收盤後到下個日盤開盤前（平日清晨、整個週末），這段時間最新的收盤是夜盤的，
    查日盤會顯示成好幾個小時前的日盤收盤價。
    """
    now = datetime.now(tz=TZ_TAIPEI)
    mins = now.hour * 60 + now.minute
    in_day_window = now.weekday() <= 4 and 8 * 60 + 45 <= mins < 15 * 60
    return not in_day_window


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
    """日期推算備援：台指期結算日固定是每月第三個星期三（未考慮國定假日順延）。
    結算日當天就切到下個月合約——結算價當天上午就固定了，本月合約形同尾盤，
    主流看盤軟體結算日當天就已經把近月報價換成下個月。
    """
    today = date.today()
    year, month = today.year, today.month
    cal       = calendar.monthcalendar(year, month)
    weds      = [w[2] for w in cal if w[2] != 0]
    third_wed = weds[2] if len(weds) >= 3 else weds[-1]
    if today >= date(year, month, third_wed):
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return f"{product}{MONTH_CODES[month - 1]}{year % 10}"


def _current_symbol(product: str = "TXF") -> str:
    """向 Fugle 查詢該商品目前上市的合約，取結算日最近且尚未結算的作為近月合約。
    比自己用「每月第三個星期三」推算更可靠（會遇到國定假日順延結算日的情況），
    查詢失敗時退回日期推算。結算日當天就排除該合約、直接算下個月——結算價當天
    上午就固定了，主流看盤軟體結算日當天就已經把近月報價換成下個月合約。
    """
    cached = _symbol_cache.get(product)
    if cached and time.time() - cached[0] < _SYMBOL_CACHE_TTL:
        return cached[1]
    try:
        data = _call_futopt(lambda c: c.futopt.intraday.tickers(type="FUTURE", product=product))
        contracts = data.get("data", [])
        today_str = date.today().strftime("%Y-%m-%d")
        upcoming = sorted(
            (c for c in contracts if c.get("settlementDate") and c.get("symbol") and c["settlementDate"] > today_str),
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


def _get_client(force_refresh: bool = False):
    global _rest_client
    if force_refresh:
        with _lock:
            _rest_client = None
    if _rest_client is None:
        with _lock:
            if _rest_client is None:
                _init_sdk()
    return _rest_client


def _call_futopt(fn):
    """呼叫富邦 SDK 的 futopt 端點。富邦登入 session 的 token 會過期（曾經遇過噴
    "Token expired" 401），但 _rest_client 是行程內快取到底，不會自動重新登入，
    導致過期後所有請求一直失敗到手動重啟服務為止。這裡抓到過期錯誤就重新登入重試一次。
    """
    try:
        return fn(_get_client())
    except Exception as e:
        msg = str(e).lower()
        if "token expired" in msg or "unauthorized" in msg or "401" in msg:
            print(f"[futures] SDK token 過期，重新登入後重試: {e}")
            return fn(_get_client(force_refresh=True))
        raise


def shutdown_sdk():
    """短命 cron 腳本（daily_update.py 等）用完 SDK 後要主動收尾，不然 init_realtime()
    啟動的背景連線元件在直譯器關閉時還活著，會噴 Fatal Python error（gilstate_tss_set）。
    常駐的 FastAPI 服務不會走到「自然結束」這一步，不需要呼叫這個函式。
    """
    global _sdk, _rest_client
    if _sdk is None:
        return
    try:
        _sdk.logout()
    except Exception as e:
        print(f"[futures] SDK logout 失敗（不影響已完成的工作）: {e}")
    finally:
        _sdk = None
        _rest_client = None


_TAIFEX_MIS_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"
# 內部代號 → 期交所 CID（app 的 TMF 剛好跟期交所微台代號一樣）
_TAIFEX_CID = {"TXF": "TXF", "TMF": "TMF"}


def _taifex_quote(symbol: str, night: bool) -> dict | None:
    """期交所公開行情的即時報價。富邦 API 在行情暴量時會落後好幾分鐘（實際遇過微台卡半小時），
    拿來交叉比對；查不到或失敗回 None，不影響原本流程。"""
    cid = _TAIFEX_CID.get(symbol[:3])
    if not cid:
        return None
    try:
        r = requests.post(_TAIFEX_MIS_URL, timeout=3, json={
            "MarketType": "1" if night else "0", "SymbolType": "F", "KindID": "1", "CID": cid,
            "ExpireMonth": "", "RowSize": "全部", "PageNo": "", "SortColumn": "", "AscDesc": "A",
        })
        rows = r.json().get("RtData", {}).get("QuoteList", [])
    except Exception as e:
        print(f"[futures] 期交所行情查詢失敗: {e}")
        return None
    num = lambda v: float(v) if v not in (None, "") else None
    for row in rows:
        # 還沒開盤時沒有成交價，但參考價（漲跌基準）一樣要拿
        if row.get("SymbolID", "").split("-")[0] == symbol:
            return {
                "price":  num(row["CLastPrice"]),
                "high":   num(row.get("CHighPrice")),
                "low":    num(row.get("CLowPrice")),
                "volume": int(num(row.get("CTotalVolume")) or 0),
                "bid":    num(row.get("CBestBidPrice")),
                "ask":    num(row.get("CBestAskPrice")),
                "symbol_id": row["SymbolID"],
                "ref":    num(row.get("CRefPrice")),
            }
    return None


def _current_session_start(now: datetime) -> datetime | None:
    """現在正在交易的那一盤的開盤時間（日盤 08:45、夜盤 15:00）；不在交易時段回 None。
    國定假日沒處理，假日由呼叫端檢查資料新鮮度擋掉。"""
    mins, wd = now.hour * 60 + now.minute, now.weekday()
    today = now.replace(second=0, microsecond=0)
    if wd <= 4 and 8 * 60 + 45 <= mins < 13 * 60 + 45:
        return today.replace(hour=8, minute=45)
    if wd <= 4 and mins >= 15 * 60:
        return today.replace(hour=15, minute=0)
    if 1 <= wd <= 5 and mins < 5 * 60:
        return (today - timedelta(days=1)).replace(hour=15, minute=0)
    return None


def _taifex_session_bars(symbol: str, tf_min: int) -> tuple[int, list] | None:
    """期交所公開行情的本盤 K 棒（由 1 分 K 依盤別開盤時間切段合併成 tf_min 分）。
    回傳 (本盤開盤 epoch, K 棒)；不在交易時段、查詢失敗或資料不新鮮回 None。"""
    now = datetime.now(tz=TZ_TAIPEI)
    start = _current_session_start(now)
    if start is None:
        return None
    night = start.hour == 15
    q = _taifex_quote(symbol, night)
    if not q:
        return None
    try:
        r = requests.post("https://mis.taifex.com.tw/futures/api/getChartData1M",
                          json={"SymbolID": q["symbol_id"]}, timeout=5)
        ticks = r.json()["RtData"]["Ticks"]
    except Exception as e:
        print(f"[futures] 期交所 1 分 K 查詢失敗: {e}")
        return None
    start_ts, step = int(start.timestamp()), tf_min * 60
    buckets: dict[int, dict] = {}
    for t, o, h, l, c, v in ticks:
        # 期交所用結束時間標記（15:01 那根 = 15:00~15:01），換成富邦的開始時間；夜盤跨午夜要 +1 天
        dt = start.replace(hour=int(t[:2]), minute=int(t[2:4]))
        if dt < start:
            dt += timedelta(days=1)
        ts = int(dt.timestamp()) - 60
        key = start_ts + (ts - start_ts) // step * step
        o, h, l, c, v = float(o), float(h), float(l), float(c), int(v)
        b = buckets.get(key)
        if b is None:
            buckets[key] = {"time": key, "open": o, "high": h, "low": l, "close": c, "volume": v}
        else:
            b["high"], b["low"], b["close"] = max(b["high"], h), min(b["low"], l), c
            b["volume"] += v
    bars = sorted(buckets.values(), key=lambda b: b["time"])
    # 假日期交所會回上一盤的舊資料，時間對不上現在就不採用
    if not bars or now.timestamp() - bars[-1]["time"] > 10 * 60 + step:
        return None
    return start_ts, bars


def _patch_with_taifex(candles: list, symbol: str, tf_min: int) -> list:
    """富邦行情暴量時 K 線會落後好幾十分鐘，本盤成交量比期交所少就整段改用期交所的 K 棒。"""
    tx = _taifex_session_bars(symbol, tf_min)
    if not tx:
        return candles
    start_ts, bars = tx
    ours = [c for c in candles if c["time"] >= start_ts]
    if sum(c.get("volume") or 0 for c in ours) >= sum(b["volume"] for b in bars):
        return candles
    return [c for c in candles if c["time"] < start_ts] + bars


def get_futures_quote(symbol: str | None = None) -> dict:
    """即時報價：日夜盤不分開顯示，自動依現在時間查目前實際在交易的那一段。"""
    symbol = symbol or _current_symbol()
    kwargs = {"symbol": symbol}
    night  = _is_night_session_now()
    if night:
        kwargs["session"] = "afterhours"
    data   = _call_futopt(lambda c: c.futopt.intraday.quote(**kwargs))
    last_trade = data.get("lastTrade") or {}
    price  = data.get("closePrice") or last_trade.get("price")
    prev   = data.get("previousClose")
    if night:
        # 夜盤 quote 的 previousClose 是前一天的舊基準，不是剛收盤的日盤價；
        # 夜盤漲跌要跟今天日盤收盤比，才是看盤軟體顯示的「新的一根」
        try:
            day = _call_futopt(lambda c: c.futopt.intraday.quote(symbol=symbol))
            prev = day.get("closePrice") or prev
        except Exception as e:
            print(f"[futures] 取日盤收盤價失敗，沿用夜盤 previousClose: {e}")
    high, low = data.get("highPrice"), data.get("lowPrice")
    volume = (data.get("total") or {}).get("tradeVolume")
    bid, ask = last_trade.get("bid"), last_trade.get("ask")
    source = "fubon"
    # 期交所成交量比富邦多 = 富邦行情落後，改用期交所的價格
    tx = _taifex_quote(symbol, night)
    if tx and tx["ref"]:
        # 漲跌基準用期交所參考價（前一日結算價），跟期交所／看盤軟體一致；
        # 富邦日盤收盤價在夜盤收盤後換日、日盤還沒開時會回錯的值（遇過算成漲 5934 點）
        prev = tx["ref"]
    if tx and tx["price"] and tx["volume"] > (volume or 0):
        price, high, low, volume, bid, ask = tx["price"], tx["high"], tx["low"], tx["volume"], tx["bid"], tx["ask"]
        source = "taifex"
    change = round(price - prev, 0) if price and prev else None
    chg_pct = round(change / prev * 100, 2) if change and prev else None
    return {
        "symbol":     symbol,
        "name":       data.get("name", "台股期貨"),
        "price":      price,
        "prev_close": prev,
        "session":    "night" if night else "day",
        "open":       data.get("openPrice"),
        "high":       high,
        "low":        low,
        "volume":     volume,
        "change":     change,
        "change_pct": chg_pct,
        # 最近一筆成交當下的最佳買/賣價（不是完整五檔，富邦期貨API沒有提供），
        # 讓使用者知道現在想買/賣大概要用什麼價位
        "bid":        bid,
        "ask":        ask,
        "source":     source,
    }


_SESSION_CLOSE_TOD = {"134500", "050000"}  # 日盤13:45／夜盤05:00收盤那一刻


def _merge_closing_tick_bars(candles: list) -> list:
    """收盤那一刻常常只剩個位數口數的官方定價成交，Fubon 會把它拆成獨立一根貼在
    13:45/05:00 整點上，K棒因此被壓成一條扁平橫線。這根本身沒有實際交易區間的意義，
    直接併回前一根：high/low 取聯集、close 用它的（才是真正官方收盤價）、量加總。
    """
    if not candles:
        return candles
    result = [dict(candles[0])]
    for c in candles[1:]:
        dt = datetime.fromtimestamp(c["time"], tz=TZ_TAIPEI)
        is_closing_tick = dt.strftime("%H%M%S") in _SESSION_CLOSE_TOD and (c.get("volume") or 0) < 500
        if is_closing_tick and result:
            prev = result[-1]
            result[-1] = {
                **prev,
                "high":   max(prev["high"], c["high"]),
                "low":    min(prev["low"], c["low"]),
                "close":  c["close"],
                "volume": (prev.get("volume") or 0) + (c.get("volume") or 0),
            }
        else:
            result.append(dict(c))
    return result


def _aggregate_1min_bars(bars: list, n: int = 2) -> list:
    """把連續的1分K每n根合併成一根（開=第一根開、收=最後一根收、high/low取聯集、量相加）。
    富邦期貨API本身沒有2分K這個週期，只能拿1分K自己併。遇到不連續（換盤別、跨日）的地方
    就從新的一組開始，不會把不同時段的K棒錯誤合併在一起。
    """
    if not bars or n <= 1:
        return bars
    result, group = [], []

    def flush():
        if group:
            result.append({
                "time":   group[0]["time"],
                "open":   group[0]["open"],
                "high":   max(b["high"] for b in group),
                "low":    min(b["low"] for b in group),
                "close":  group[-1]["close"],
                "volume": sum(b.get("volume") or 0 for b in group),
            })

    for b in bars:
        if group and (b["time"] - group[-1]["time"] != 60 or len(group) >= n):
            flush()
            group = []
        group.append(b)
    flush()
    return result


def get_futures_candles(symbol: str | None = None, timeframe: str = "60") -> list:
    """K 線：日盤＋夜盤接續成一條連續走勢，不分開查。"""
    symbol = symbol or _current_symbol()

    if timeframe == "2":
        return _aggregate_1min_bars(get_futures_candles(symbol, "1"), 2)

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
                data = _call_futopt(lambda c: c.futopt.intraday.candles(**kwargs))
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
        tx = _taifex_session_bars(symbol, 60)
        if tx:
            start_ts, bars = tx
            day_key = _trading_day_of(start_ts)
            cur = {t: c for t, c in grouped.get(day_key, {}).items() if t >= start_ts}
            if sum(c.get("volume") or 0 for c in cur.values()) < sum(b["volume"] for b in bars):
                kept = {t: c for t, c in grouped.get(day_key, {}).items() if t < start_ts}
                grouped[day_key] = {**kept, **{b["time"]: b for b in bars}}
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
            data = _call_futopt(lambda c: c.futopt.intraday.candles(**kwargs))
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
    today_candles = _patch_with_taifex(sorted(today_candles.values(), key=lambda c: c["time"]), symbol, int(timeframe))

    # DB 歷史資料：日盤／夜盤共用同一個 (product, timeframe) 存放，時間本來就不重疊，
    # 直接接續成一條連續走勢
    hist = get_futures_candles_db(product, timeframe)
    if today_candles:
        today_min_time = today_candles[0]["time"]
        hist = [c for c in hist if c["time"] < today_min_time]

    return _merge_closing_tick_bars(hist + today_candles)


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

from app.services.fubon_ws_reconnect import connect_client, start_reconnect

# symbol → set of asyncio.Queue（每個連線一個 queue）
_ws_queues: dict[str, set] = {}
_ws_lock = threading.Lock()
_ws_futopt = None   # Fubon WS futopt client（全域共用）


_ws_futopt_handlers_on = None   # 已註冊 callback 的 client；SDK 的 on() 會累加，同一個 client 只能註冊一次


def _reset_ws_futopt():
    """Fubon WS 斷線時重置，有人在看就背景自動重連並補回訂閱。"""
    global _ws_futopt
    # 先不拿鎖判斷：重連過程中舊連線的 close 事件會在持鎖期間觸發，等鎖會在新連線建好後誤把它重置掉
    if _ws_futopt is None:
        return
    with _lock:
        if _ws_futopt is None:
            return
        _ws_futopt = None
    print("[Fubon WS] 期貨連線已重置")
    start_reconnect("期貨", _reconnect_ws_futopt)


def _reconnect_ws_futopt():
    with _ws_lock:
        if not any(_ws_queues.values()):
            return   # 沒人訂閱就不重連，等下次請求再建
    _get_ws_futopt()


def _get_ws_futopt():
    """取得 Fubon WebSocket futopt client，確保已登入並連線。"""
    global _ws_futopt, _ws_futopt_handlers_on
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
                    loop.call_soon_threadsafe(q.put_nowait, payload)
                except Exception:
                    pass

        def _on_disconnect(*msg):   # SDK 會傳 (code, reason) 兩個參數
            print(f"[Fubon WS] 斷線: {msg}")
            _reset_ws_futopt()

        if _ws_futopt_handlers_on is not futopt:   # token 過期重新登入後會換新 client
            futopt.on("message", _on_message)
            # 有些版本提供 disconnect / error / close 事件
            for evt in ("disconnect", "error", "close"):
                try:
                    futopt.on(evt, _on_disconnect)
                except Exception:
                    pass
            _ws_futopt_handlers_on = futopt
        connect_client(futopt)
        time.sleep(2)   # 等連線建立後再 return（connect() 是非同步啟動）
        # 重連時把訂閱過的商品全部補回來（期貨端離開不取消訂閱，空的也要補，之後有人進來才收得到）
        with _ws_lock:
            resub = list(_ws_queues)
        for sym in resub:
            try:
                futopt.subscribe({"channel": "trades", "symbol": sym})
                futopt.subscribe({"channel": "quote",  "symbol": sym})
            except Exception as e:
                print(f"[Fubon WS] 重新訂閱 {sym} 失敗: {e}")
        _ws_futopt = futopt
        print(f"[Fubon WS] 期貨連線已建立（補訂閱 {len(resub)} 檔）")
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
