"""追蹤快速篩選訊號的後續表現（5/10/20 個交易日報酬率），評估各篩選條件是否真的有效。"""
from datetime import date, timedelta

from app.db import (
    save_scan_signals, get_signals_pending_evaluation, update_signal_returns,
    get_scan_signal_stats, get_recent_scan_signals, get_candles,
    upsert_ema60_watch, get_ema60_watchlist, remove_ema60_watch, prune_stale_ema60_watch,
    log_ema60_watch_events, get_ema60_watch_events,
    mark_ema60_breakout_invalidated, get_ema60_breakout_invalidated,
)

SCAN_LABELS = {
    "weekly_surge":          "週漲幅急漲",
    "bird_beak":              "鳥嘴與分歧",
    "near_ema60":             "EMA60近線",
    "volume_breakout":        "量價突破",
    "institutional_buying":   "法人連買",
    "ema60_breakout":         "EMA60貼線噴出",
    "ut_bot_long":            "UT Bot 多單",
    "ut_bot_short":           "UT Bot 空單",
    "supertrend_long":        "SuperTrend 多單",
    "supertrend_short":       "SuperTrend 空單",
    "volume_breakout_loose":  "量價突破(寬鬆)",
    "rs_momentum":            "RS動能",
}

# 大部分篩選都是「看多」訊號，報酬率正的算贏；空單訊號方向相反，跌才算贏，
# 統計時要把報酬率符號反過來才能跟其他篩選用同一套「正的=贏」邏輯比較。
SCAN_DIRECTION = {"ut_bot_short": -1, "supertrend_short": -1}

# 期貨（大台指/微台指）訊號的日K要從期貨自己的資料來源拿，不是股票的 candles 表
FUTURES_SCAN_TYPES = {"ut_bot_long", "ut_bot_short", "supertrend_long", "supertrend_short"}


def _futures_daily_candles(product: str) -> list[dict]:
    from app.services.futures_data import get_futures_candles
    rows = get_futures_candles(product, "D")
    return [{"date": r["date"], "close": r["close"]} for r in rows]


def record_signals(scan_type: str, hits: list):
    """每次排程掃描出結果時呼叫，把當天命中的股票存一筆快照（同股票同天同類型只存一次）。"""
    today = date.today().strftime("%Y-%m-%d")
    records = [
        {
            "ticker": h["ticker"],
            "name": h.get("name", ""),
            "scan_type": scan_type,
            "signal_date": today,
            "signal_price": h.get("close") or h.get("price"),
        }
        for h in hits if h.get("close") or h.get("price")
    ]
    save_scan_signals(records)


def _pct_change(base: float, new: float) -> float:
    return round((new - base) / base * 100, 2)


def evaluate_pending_signals():
    """把訊號日之後累積夠 K 棒的訊號，用之後的收盤價補上 5/10/20 個交易日報酬率。
    用交易日根數（而非日曆天數）取樣，才不會被假日拖累。
    """
    today_str = date.today().strftime("%Y-%m-%d")
    for sig in get_signals_pending_evaluation():
        if not sig.get("signal_price"):
            continue
        if sig["scan_type"] in FUTURES_SCAN_TYPES:
            try:
                candles = _futures_daily_candles(sig["ticker"])
            except Exception as e:
                print(f"[篩選成效] 取得 {sig['ticker']} 期貨日K失敗: {e}")
                continue
        else:
            candles = get_candles(sig["ticker"], sig["signal_date"], today_str)
        after = [c for c in candles if c["date"] > sig["signal_date"] and c.get("close") is not None]

        def price_at(idx):
            return after[idx]["close"] if len(after) > idx else None

        base = sig["signal_price"]
        p5, p10, p20 = price_at(4), price_at(9), price_at(19)
        r5  = _pct_change(base, p5)  if p5  is not None else None
        r10 = _pct_change(base, p10) if p10 is not None else None
        r20 = _pct_change(base, p20) if p20 is not None else None
        if r5 is not None or r10 is not None or r20 is not None:
            update_signal_returns(sig["id"], r5, r10, r20)


EMA60_WATCH_EXPIRY_DAYS = 21  # 太久沒再貼近EMA60、也一直沒噴出的股票，型態視為失效，從觀察名單清掉


def update_ema60_watchlist(hits: list):
    """把今天 EMA60近線 掃到的股票加進觀察名單；已經在名單裡的只刷新 last_seen（不重複計入）。
    真正新加入的記一筆 added 事件，供週報統計「本週新加入」用。
    """
    today = date.today().strftime("%Y-%m-%d")
    added_events = []
    for h in hits:
        if not h.get("ticker"):
            continue
        is_new = upsert_ema60_watch(h["ticker"], h.get("name", ""), today, h.get("close"))
        if is_new:
            added_events.append({
                "ticker": h["ticker"], "name": h.get("name", ""),
                "event_type": "added", "reason": None, "event_date": today,
            })
    log_ema60_watch_events(added_events)


EMA60_BREAKOUT_TRACKING_DAYS = 30  # 噴出追蹤清單只看最近30天內觸發的，太久之前的不繼續佔畫面
EMA60_BREAKOUT_COOLDOWN_DAYS = 20  # 噴出後這麼多天內不重複記錄，避免同一次型態被算成好幾次噴出


def check_ema60_breakouts() -> list[dict]:
    """檢查觀察名單裡的股票今天有沒有「噴出」：
    (a) 爆量：今日量 ≥ 近5日均量 3倍
    (b) 站回EMA10：昨天收盤 < 昨天EMA10，今天收盤 ≥ 今天EMA10（由下往上穿越，不是單純「現在站上」）
    任一條件觸發就算噴出：記錄一筆訊號快照（供噴出後繼續追蹤表現、以及5/10/20日報酬率評估用）、
    從觀察名單移除（已經噴出，不用再等下一次噴出通知）。同時清掉太久沒動靜的股票。

    冷卻期：噴出後股價常常還黏在EMA60附近，隔幾天又被「EMA60近線」掃描抓回觀察名單，這時候
    如果又被爆量或EMA10微幅交叉這種雜訊等級的訊號觸發，不該算成一次新的噴出——所以
    EMA60_BREAKOUT_COOLDOWN_DAYS 天內已經噴出過的股票，就算又跑回觀察名單也先跳過、
    順便把它從觀察名單移除（冷卻期內不用一直重複判斷同一支）。

    型態失效：EMA10 已經跌到 EMA60 之下（不限於今天剛跌破，只要現在還處於這個狀態就算），
    代表原本貼線緩漲的型態已經走弱、不會再噴出了，直接從觀察名單移除，不算噴出也不記錄訊號
    （單純退出觀察，不是要追蹤的結果）。用「現在的狀態」而非「今天剛好跨越」判斷，這樣才能
    抓到「幾天前就已經跌破、但那天剛好還沒有這個規則」的既有觀察名單成員。

    回傳觸發清單，供排程發 Telegram 通知用。
    """
    watchlist = get_ema60_watchlist()
    if not watchlist:
        return []

    today_str  = date.today().strftime("%Y-%m-%d")
    from_date  = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")  # 120天確保有足夠K棒算EMA60
    cooldown_since = (date.today() - timedelta(days=EMA60_BREAKOUT_COOLDOWN_DAYS)).strftime("%Y-%m-%d")
    recent_breakout_tickers = {r["ticker"] for r in get_recent_scan_signals("ema60_breakout", cooldown_since)}
    name_map = {w["ticker"]: w.get("name", "") for w in watchlist}

    def _log_removed(tickers: list[str], reason: str):
        log_ema60_watch_events([
            {"ticker": t, "name": name_map.get(t, ""), "event_type": "removed",
             "reason": reason, "event_date": today_str}
            for t in tickers
        ])

    triggered = []
    invalidated = []
    cooling_down = [w["ticker"] for w in watchlist if w["ticker"] in recent_breakout_tickers]
    if cooling_down:
        remove_ema60_watch(cooling_down)
        _log_removed(cooling_down, "cooldown")

    for w in watchlist:
        ticker = w["ticker"]
        if ticker in recent_breakout_tickers:
            continue
        records = get_candles(ticker, from_date, today_str)
        if not records or len(records) < 62:
            continue

        closes = [r["close"] for r in records if r["close"] is not None]
        if len(closes) < 62:
            continue

        k10, ema10 = 2 / 11, None
        k60, ema60 = 2 / 61, None
        ema10_series, ema60_series = [], []
        for c in closes:
            ema10 = c if ema10 is None else c * k10 + ema10 * (1 - k10)
            ema60 = c if ema60 is None else c * k60 + ema60 * (1 - k60)
            ema10_series.append(ema10)
            ema60_series.append(ema60)

        today_close, today_ema10, today_ema60 = closes[-1], ema10_series[-1], ema60_series[-1]
        prev_close,  prev_ema10  = closes[-2], ema10_series[-2]

        if today_ema10 < today_ema60:
            invalidated.append(ticker)
            continue

        today_vol = records[-1].get("volume") or 0
        recent5   = records[-6:-1]
        vols5     = [r.get("volume") or 0 for r in recent5]
        avg_vol_5d = sum(vols5) / len(vols5) if len(vols5) == 5 else 0
        vol_ratio  = today_vol / avg_vol_5d if avg_vol_5d > 0 else 0
        volume_trigger = vol_ratio >= 3.0

        ema10_cross_trigger = prev_close < prev_ema10 and today_close >= today_ema10

        if not (volume_trigger or ema10_cross_trigger):
            continue

        reasons = []
        if volume_trigger:
            reasons.append(f"爆量（今日量為近5日均量 {round(vol_ratio, 1)} 倍）")
        if ema10_cross_trigger:
            reasons.append("站回 EMA10")
        triggered.append({
            "ticker": ticker, "name": w.get("name", ""),
            "close": today_close, "entry_price": w.get("entry_price"),
            "reasons": reasons,
        })

    if invalidated:
        print(f"[EMA60貼線] EMA10跌破EMA60，型態失效移除觀察名單: {invalidated}")
        remove_ema60_watch(invalidated)
        _log_removed(invalidated, "death_cross")

    if triggered:
        record_signals("ema60_breakout", triggered)
        remove_ema60_watch([t["ticker"] for t in triggered])
        _log_removed([t["ticker"] for t in triggered], "breakout")

    cutoff = (date.today() - timedelta(days=EMA60_WATCH_EXPIRY_DAYS)).strftime("%Y-%m-%d")
    stale_removed = prune_stale_ema60_watch(cutoff)
    if stale_removed:
        log_ema60_watch_events([
            {"ticker": r["ticker"], "name": r.get("name", ""), "event_type": "removed",
             "reason": "stale", "event_date": today_str}
            for r in stale_removed
        ])

    return triggered


def check_ema60_breakout_invalidations() -> list[dict]:
    """檢查「貼線噴出追蹤」清單裡的股票，EMA10 是否已經跌破 EMA60（噴出後動能失效、
    走勢又轉弱了）。失效的標記起來，之後 get_ema60_breakout_tracking() 不會再顯示它，
    同時記一筆 removed 事件（source=breakout_tracking）供週報使用。

    注意：只標記，不動 scan_signals 本身——5/10/20日報酬率統計要用全部訊號（含失效的）
    才不會有存活者偏誤，讓「EMA60貼線噴出」這個訊號來源的勝率看起來比實際更好。

    回傳新失效的清單，供排程發 Telegram 通知用。
    """
    today_str = date.today().strftime("%Y-%m-%d")
    since = (date.today() - timedelta(days=EMA60_BREAKOUT_TRACKING_DAYS)).strftime("%Y-%m-%d")
    from_date = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")

    rows = get_recent_scan_signals("ema60_breakout", since)
    if not rows:
        return []
    already_invalidated = get_ema60_breakout_invalidated(since)

    newly_invalidated = []
    for r in rows:
        key = (r["ticker"], r["signal_date"])
        if key in already_invalidated:
            continue
        records = get_candles(r["ticker"], from_date, today_str)
        closes = [c["close"] for c in records if c.get("close") is not None]
        if len(closes) < 62:
            continue

        k10, ema10 = 2 / 11, None
        k60, ema60 = 2 / 61, None
        for c in closes:
            ema10 = c if ema10 is None else c * k10 + ema10 * (1 - k10)
            ema60 = c if ema60 is None else c * k60 + ema60 * (1 - k60)

        if ema10 < ema60:
            newly_invalidated.append({"ticker": r["ticker"], "name": r.get("name", ""), "signal_date": r["signal_date"]})

    if newly_invalidated:
        print(f"[EMA60噴出追蹤] EMA10跌破EMA60，動能失效: {[x['ticker'] for x in newly_invalidated]}")
        mark_ema60_breakout_invalidated([(x["ticker"], x["signal_date"]) for x in newly_invalidated])
        log_ema60_watch_events([
            {"ticker": x["ticker"], "name": x["name"], "event_type": "removed", "reason": "death_cross",
             "source": "breakout_tracking", "event_date": today_str}
            for x in newly_invalidated
        ])

    return newly_invalidated


def get_ema60_watchlist_view() -> list[dict]:
    """觀察名單 + 即時報價，供前端「EMA60貼線觀察名單」頁面顯示用。
    依加入觀察名單的日期新到舊排序（最新盯上的排最前面）。
    """
    from app.services.stock_data import get_watchlist_quotes
    rows = get_ema60_watchlist()
    if not rows:
        return []
    quote_map = {q["ticker"]: q for q in get_watchlist_quotes([r["ticker"] for r in rows])}
    result = []
    for r in rows:
        q = quote_map.get(r["ticker"], {})
        close = q.get("close")
        entry = r.get("entry_price")
        since_entry_pct = round((close - entry) / entry * 100, 2) if close and entry else None
        result.append({
            "ticker":           r["ticker"],
            "name":             r.get("name") or q.get("name") or "",
            "first_seen_date":  r["first_seen_date"],
            "last_seen_date":   r["last_seen_date"],
            "entry_price":      entry,
            "price":            close,
            "change_pct":       q.get("change_pct"),
            "since_entry_pct":  since_entry_pct,
        })
    result.sort(key=lambda x: x["first_seen_date"], reverse=True)
    return result


def get_ema60_breakout_tracking() -> list[dict]:
    """最近觸發「EMA60貼線噴出」的股票 + 即時報價，噴出後不會消失，繼續放這裡讓你觀察後續表現
    （5/10/20 個交易日報酬率會隨時間自動補上）。只看最近 EMA60_BREAKOUT_TRACKING_DAYS 天內觸發的，
    依觸發日期新到舊排序。EMA10已經跌破EMA60（噴出動能失效）的會被 check_ema60_breakout_invalidations()
    標記起來，這裡過濾掉不顯示——但底層 scan_signals 資料還在，5/10/20日報酬率統計不受影響。
    """
    from app.services.stock_data import get_watchlist_quotes
    since = (date.today() - timedelta(days=EMA60_BREAKOUT_TRACKING_DAYS)).strftime("%Y-%m-%d")
    rows = get_recent_scan_signals("ema60_breakout", since)
    if not rows:
        return []
    invalidated = get_ema60_breakout_invalidated(since)
    rows = [r for r in rows if (r["ticker"], r["signal_date"]) not in invalidated]
    if not rows:
        return []
    quote_map = {q["ticker"]: q for q in get_watchlist_quotes([r["ticker"] for r in rows])}
    result = []
    for r in rows:
        q = quote_map.get(r["ticker"], {})
        price  = q.get("close")
        entry  = r.get("signal_price")
        since_trigger_pct = round((price - entry) / entry * 100, 2) if price and entry else None
        result.append({
            "ticker":            r["ticker"],
            "name":              r.get("name") or q.get("name") or "",
            "trigger_date":      r["signal_date"],
            "trigger_price":     entry,
            "price":             price,
            "change_pct":        q.get("change_pct"),
            "since_trigger_pct": since_trigger_pct,
            "return_5d":         r.get("return_5d"),
            "return_10d":        r.get("return_10d"),
            "return_20d":        r.get("return_20d"),
        })
    return result


EMA60_REMOVE_REASON_LABEL = {
    "breakout":    "噴出",
    "death_cross": "EMA10跌破EMA60",
    "cooldown":    "噴出冷卻期內",
    "stale":       "太久沒動靜",
}


def get_ema60_weekly_report(days: int = 7) -> dict:
    """EMA60貼線觀察名單週報：目前還在觀察的、近N天新加入的、近N天被移除的（含原因），
    以及「貼線噴出追蹤」清單近N天因EMA10跌破EMA60而被標記失效的。供排程發 Telegram 週報用。
    """
    since = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    events = get_ema60_watch_events(since)
    added = [e for e in events if e["event_type"] == "added"]
    removed = [
        {**e, "reason_label": EMA60_REMOVE_REASON_LABEL.get(e["reason"], e["reason"] or "—")}
        for e in events if e["event_type"] == "removed" and e.get("source", "watchlist") == "watchlist"
    ]
    tracking_removed = [
        {**e, "reason_label": EMA60_REMOVE_REASON_LABEL.get(e["reason"], e["reason"] or "—")}
        for e in events if e["event_type"] == "removed" and e.get("source") == "breakout_tracking"
    ]
    watching = get_ema60_watchlist()
    watching.sort(key=lambda w: w["first_seen_date"], reverse=True)
    return {
        "still_watching": watching, "added": added, "removed": removed,
        "tracking_removed": tracking_removed,
    }


def _avg(vals: list) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def get_performance_summary(days: int = 90) -> list[dict]:
    """近 N 天各篩選類型的成效統計：訊號數、20日勝率、平均報酬（5/10/20日）。
    只統計 return_20d 已算出的訊號（代表訊號日至今已滿 20 個交易日，資料完整可比較）。
    """
    from datetime import timedelta
    since = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    summary = []
    for scan_type, label in SCAN_LABELS.items():
        rows = get_scan_signal_stats(scan_type, since)
        if not rows:
            continue
        direction = SCAN_DIRECTION.get(scan_type, 1)
        n = len(rows)
        win = sum(1 for r in rows if r["return_20d"] is not None and r["return_20d"] * direction > 0)
        flip = lambda v: v * direction if v is not None else None
        summary.append({
            "scan_type": scan_type,
            "label": label,
            "count": n,
            "win_rate": round(win / n * 100, 1),
            "avg_return_5d":  _avg([flip(r["return_5d"])  for r in rows]),
            "avg_return_10d": _avg([flip(r["return_10d"]) for r in rows]),
            "avg_return_20d": _avg([flip(r["return_20d"]) for r in rows]),
        })
    return summary


def get_signal_overview(days: int = 180) -> list[dict]:
    """給「訊號績效總覽」頁用：每個篩選類型目前累積了多少訊號、各期報酬率目前算得出來的
    部分平均值。跟 get_performance_summary 不同的地方是不用等 20 日報酬率全部到齊才顯示
    ——訊號剛滿5天但還沒滿20天時，5日報酬率已經看得到，這樣才能在訊號還在累積階段就看到
    部分結果，不用整個乾等好幾週。
    """
    from datetime import timedelta
    since = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    summary = []
    for scan_type, label in SCAN_LABELS.items():
        rows = get_recent_scan_signals(scan_type, since, limit=2000)
        if not rows:
            continue
        direction = SCAN_DIRECTION.get(scan_type, 1)
        flip = lambda v: v * direction if v is not None else None
        mature = [r for r in rows if r["return_20d"] is not None]
        win = sum(1 for r in mature if flip(r["return_20d"]) > 0)
        summary.append({
            "scan_type":      scan_type,
            "label":          label,
            "count":          len(rows),
            "mature_count":   len(mature),
            "win_rate":       round(win / len(mature) * 100, 1) if mature else None,
            "avg_return_5d":  _avg([flip(r["return_5d"])  for r in rows if r["return_5d"]  is not None]),
            "avg_return_10d": _avg([flip(r["return_10d"]) for r in rows if r["return_10d"] is not None]),
            "avg_return_20d": _avg([flip(r["return_20d"]) for r in rows if r["return_20d"] is not None]),
        })
    summary.sort(key=lambda x: x["count"], reverse=True)
    return summary
