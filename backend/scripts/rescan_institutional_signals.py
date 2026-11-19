"""
重掃歷史「法人連買」訊號（institutional_buying）。
三大法人資料補齊或修正後跑這支，讓策略成績單用正確的資料計算。

對每個交易日：用當天為基準重新掃描，刪掉不再命中的舊訊號、補上新命中的訊號；
原本就正確的訊號保留（連同已算好的 5/10/20 日報酬），最後補算新訊號的報酬。

用法：
  python3 scripts/rescan_institutional_signals.py 2026-07-23 2026-11-18
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

from datetime import date

from app.db import _conn, get_candles
from app.services.stock_data import scan_institutional_buying
from app.services.signal_tracking import record_signals, evaluate_pending_signals

SCAN_TYPE = "institutional_buying"
start, end = sys.argv[1], sys.argv[2]

# 用台積電日K當交易日曆
trading_days = [c["date"] for c in get_candles("2330", start, end)]
added_total = removed_total = 0

for day_iso in trading_days:
    # 參數要跟 daily_update.py 的排程一致
    hits = scan_institutional_buying(min_days=3, limit=200, min_total_net_zhang=5000,
                                     as_of=date.fromisoformat(day_iso))
    new_set = {h["ticker"] for h in hits}
    with _conn() as conn:
        old_set = {r[0] for r in conn.execute(
            "SELECT ticker FROM scan_signals WHERE scan_type=? AND signal_date=?", (SCAN_TYPE, day_iso))}
        stale = old_set - new_set
        conn.executemany(
            "DELETE FROM scan_signals WHERE scan_type=? AND signal_date=? AND ticker=?",
            [(SCAN_TYPE, day_iso, t) for t in stale])
    record_signals(SCAN_TYPE, hits, signal_date=day_iso)
    added = len(new_set - old_set)
    added_total += added
    removed_total += len(stale)
    print(f"{day_iso}: 命中 {len(new_set)}（原 {len(old_set)}，新增 {added}、移除 {len(stale)}）")

print(f"合計新增 {added_total}、移除 {removed_total}")
evaluate_pending_signals()
print("已補算報酬")
