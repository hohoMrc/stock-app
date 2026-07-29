"""追蹤快速篩選訊號的後續表現（5/10/20 個交易日報酬率），評估各篩選條件是否真的有效。"""
from datetime import date, timedelta

from app.db import (
    save_scan_signals, get_signals_pending_evaluation, update_signal_returns,
    get_scan_signal_stats, get_candles,
    upsert_ema60_watch, get_ema60_watchlist, remove_ema60_watch, prune_stale_ema60_watch,
)

SCAN_LABELS = {
    "weekly_surge":          "週漲幅急漲",
    "bird_beak":              "鳥嘴與分歧",
    "near_ema60":             "EMA60近線",
    "volume_breakout":        "量價突破",
    "institutional_buying":   "法人連買",
}


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
    """把今天 EMA60近線 掃到的股票加進觀察名單；已經在名單裡的只刷新 last_seen（不重複計入）。"""
    today = date.today().strftime("%Y-%m-%d")
    for h in hits:
        if not h.get("ticker"):
            continue
        upsert_ema60_watch(h["ticker"], h.get("name", ""), today, h.get("close"))


def check_ema60_breakouts() -> list[dict]:
    """檢查觀察名單裡的股票今天有沒有「噴出」：
    (a) 爆量：今日量 ≥ 近5日均量 3倍
    (b) 站回EMA10：昨天收盤 < 昨天EMA10，今天收盤 ≥ 今天EMA10（由下往上穿越，不是單純「現在站上」）
    任一條件觸發就算噴出，從觀察名單移除（不重複通知）。同時清掉太久沒動靜的股票。
    回傳觸發清單，供排程發 Telegram 通知用。
    """
    watchlist = get_ema60_watchlist()
    if not watchlist:
        return []

    today_str  = date.today().strftime("%Y-%m-%d")
    from_date  = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")

    triggered = []
    for w in watchlist:
        ticker = w["ticker"]
        records = get_candles(ticker, from_date, today_str)
        if not records or len(records) < 12:
            continue

        today_vol = records[-1].get("volume") or 0
        recent5   = records[-6:-1]
        vols5     = [r.get("volume") or 0 for r in recent5]
        avg_vol_5d = sum(vols5) / len(vols5) if len(vols5) == 5 else 0
        vol_ratio  = today_vol / avg_vol_5d if avg_vol_5d > 0 else 0
        volume_trigger = vol_ratio >= 3.0

        closes = [r["close"] for r in records if r["close"] is not None]
        if len(closes) < 2:
            continue
        k, ema = 2 / 11, None
        ema_series = []
        for c in closes:
            ema = c if ema is None else c * k + ema * (1 - k)
            ema_series.append(ema)
        today_close, today_ema10 = closes[-1], ema_series[-1]
        prev_close,  prev_ema10  = closes[-2], ema_series[-2]
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

    if triggered:
        remove_ema60_watch([t["ticker"] for t in triggered])

    cutoff = (date.today() - timedelta(days=EMA60_WATCH_EXPIRY_DAYS)).strftime("%Y-%m-%d")
    prune_stale_ema60_watch(cutoff)

    return triggered


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
        n = len(rows)
        win = sum(1 for r in rows if r["return_20d"] is not None and r["return_20d"] > 0)
        summary.append({
            "scan_type": scan_type,
            "label": label,
            "count": n,
            "win_rate": round(win / n * 100, 1),
            "avg_return_5d":  _avg([r["return_5d"]  for r in rows]),
            "avg_return_10d": _avg([r["return_10d"] for r in rows]),
            "avg_return_20d": _avg([r["return_20d"] for r in rows]),
        })
    return summary
