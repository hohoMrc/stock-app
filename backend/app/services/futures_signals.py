"""UT Bot 訊號（ATR 移動停損翻轉系統）：每天排程檢查一次大台指/微台指的日K有沒有觸發
buy/sell，觸發就記錄一筆快照，之後用既有的 signal_tracking 機制驗證 5/10/20 個交易日報酬率。

參數是拿使用者提供的 TradingView Pine Script（UT Bot Strategy, a=1 c=11）回測後調整的：
把 Key Value 從 1 拉高到 2，大幅減少雜訊翻倉；EMA60濾網／允許空手兩個方向回測後效果
不穩定（甚至變差），所以沒有採用。
"""
from app.services.futures_data import get_futures_candles
from app.services.signal_tracking import record_signals

UT_BOT_A          = 2    # Key Value（回測後採用，原版 a=1 太敏感）
UT_BOT_ATR_PERIOD = 11
PRODUCT_LABEL     = {"TXF": "大台指", "TMF": "微台指"}


def _true_range(bars: list[dict]) -> list[float]:
    tr = [bars[0]["high"] - bars[0]["low"]]
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return tr


def _rma(values: list[float], period: int) -> list[float | None]:
    """Wilder's smoothing，Pine 的 atr() 內部就是用這個，不是一般 EMA。"""
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    for i in range(period, len(values)):
        result[i] = (result[i - 1] * (period - 1) + values[i]) / period
    return result


def _ut_bot_last_signal(bars: list[dict]) -> str | None:
    """算完整序列的 ATR 移動停損線，回傳「最後一根」是否剛好觸發 buy/sell（None 代表沒有）。"""
    closes = [b["close"] for b in bars]
    atr = _rma(_true_range(bars), UT_BOT_ATR_PERIOD)
    n = len(bars)
    stop: list[float | None] = [None] * n
    first_valid = None
    last_signal = None

    for i in range(n):
        if atr[i] is None:
            continue
        src = closes[i]
        n_loss = UT_BOT_A * atr[i]
        if first_valid is None:
            stop[i] = src - n_loss
            first_valid = i
            continue
        prev_stop, prev_src = stop[i - 1], closes[i - 1]
        if src > prev_stop and prev_src > prev_stop:
            stop[i] = max(prev_stop, src - n_loss)
        elif src < prev_stop and prev_src < prev_stop:
            stop[i] = min(prev_stop, src + n_loss)
        else:
            stop[i] = src - n_loss if src > prev_stop else src + n_loss

        crossover_up   = src > stop[i] and prev_src <= prev_stop
        crossover_down = stop[i] > src and prev_stop <= prev_src
        if i == n - 1:
            if src > stop[i] and crossover_up:
                last_signal = "buy"
            elif src < stop[i] and crossover_down:
                last_signal = "sell"

    return last_signal


def check_ut_bot_signals() -> list[dict]:
    """每天排程呼叫一次：大台指、微台指的日K各檢查一次今天有沒有觸發訊號。
    多單(buy)、空單(sell)分開記錄成 ut_bot_long / ut_bot_short 兩種 scan_type，
    因為看對的方向不同（多單要漲、空單要跌才算贏），5/10/20日報酬率評估時要分開處理。
    回傳這一輪觸發的清單，供排程腳本發 TG 通知用。
    """
    triggered = []
    for product in ("TXF", "TMF"):
        try:
            bars = get_futures_candles(product, "D")
        except Exception as e:
            print(f"[UT Bot] 取得 {product} 日K失敗: {e}")
            continue
        if len(bars) < UT_BOT_ATR_PERIOD + 5:
            continue

        signal = _ut_bot_last_signal(bars)
        if not signal:
            continue

        last = bars[-1]
        hit = {
            "ticker": product, "name": PRODUCT_LABEL[product],
            "close": last["close"], "side": signal,
        }
        scan_type = "ut_bot_long" if signal == "buy" else "ut_bot_short"
        record_signals(scan_type, [hit])
        triggered.append({**hit, "scan_type": scan_type})

    return triggered


def get_ut_bot_tracking(days: int = 30) -> list[dict]:
    """最近 N 天觸發過的 UT Bot 訊號 + 即時報價，供前端顯示追蹤用。"""
    from datetime import date, timedelta
    from app.services.signal_tracking import get_recent_scan_signals
    from app.services.futures_data import get_futures_quote, _current_symbol

    since = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = []
    for scan_type, side_label in (("ut_bot_long", "多"), ("ut_bot_short", "空")):
        for r in get_recent_scan_signals(scan_type, since):
            rows.append({**r, "side": side_label, "scan_type": scan_type})
    if not rows:
        return []

    quote_cache: dict[str, float | None] = {}
    result = []
    for r in rows:
        product = r["ticker"]
        if product not in quote_cache:
            try:
                quote_cache[product] = get_futures_quote(_current_symbol(product)).get("price")
            except Exception:
                quote_cache[product] = None
        price = quote_cache[product]
        entry = r.get("signal_price")
        is_short = r["scan_type"] == "ut_bot_short"
        since_pct = None
        if price and entry:
            since_pct = round((price - entry) / entry * 100, 2)
            if is_short:
                since_pct = -since_pct   # 空單方向相反，跌才是賺

        def _flip(v):
            return -v if (v is not None and is_short) else v

        result.append({
            "product":           product,
            "name":              PRODUCT_LABEL.get(product, product),
            "side":              r["side"],
            "trigger_date":      r["signal_date"],
            "trigger_price":     entry,
            "price":             price,
            "since_trigger_pct": since_pct,
            "return_5d":         _flip(r.get("return_5d")),
            "return_10d":        _flip(r.get("return_10d")),
            "return_20d":        _flip(r.get("return_20d")),
        })
    result.sort(key=lambda x: x["trigger_date"], reverse=True)
    return result
