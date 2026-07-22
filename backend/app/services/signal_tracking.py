"""追蹤快速篩選訊號的後續表現（5/10/20 個交易日報酬率），評估各篩選條件是否真的有效。"""
from datetime import date

from app.db import (
    save_scan_signals, get_signals_pending_evaluation, update_signal_returns,
    get_scan_signal_stats, get_candles,
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
