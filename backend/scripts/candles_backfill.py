"""
日K歷史回補：把 DB 裡每檔股票的日K往前補到指定天數（預設 600 天，約 80 週），
讓週K 54MA 這類長週期指標算得出來。只補「該檔目前最早一筆之前」的空缺，不覆蓋既有資料，
中斷後重跑會自動接續。

Fugle historical candles 限制：單次區間要「少於一年」、60 次/分鐘（排程也共用這個額度），
所以每次抓 360 天、整體壓在約 50 次/分鐘。
用法：
  python3 scripts/candles_backfill.py          # 補到 600 天前
  python3 scripts/candles_backfill.py 700      # 自訂天數
"""
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

from datetime import date, timedelta
from app.db import _conn, save_candles
from app.services.stock_data import _fugle_candles

CHUNK_DAYS   = 360
MIN_INTERVAL = 60 / 50   # 每次請求至少間隔 1.2 秒


def main():
    days  = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    start = date.today() - timedelta(days=days)

    with _conn() as conn:
        rows = conn.execute("SELECT ticker, MIN(date) AS first FROM candles GROUP BY ticker ORDER BY ticker").fetchall()
    # 最早一筆已經在目標日期一週內的就不用補（前面可能剛好是假日）
    todo = [(r["ticker"], date.fromisoformat(r["first"])) for r in rows
            if date.fromisoformat(r["first"]) > start + timedelta(days=7)]
    print(f"[回補] 目標起始日 {start}，共 {len(rows)} 檔，需補 {len(todo)} 檔", flush=True)

    last_call = 0.0
    added_total = 0
    for i, (ticker, first) in enumerate(todo, 1):
        added = 0
        end = first - timedelta(days=1)
        # 從既有最早日期往回一段一段抓，抓到空的就代表更早沒資料（例如新上市），直接停
        while end > start:
            chunk_from = max(start, end - timedelta(days=CHUNK_DAYS - 1))
            wait = MIN_INTERVAL - (time.time() - last_call)
            if wait > 0:
                time.sleep(wait)
            last_call = time.time()
            records = _fugle_candles(ticker, chunk_from.isoformat(), end.isoformat())
            if not records:
                break
            save_candles(ticker, records)
            added += len(records)
            end = chunk_from - timedelta(days=1)
        added_total += added
        if i % 50 == 0 or i == len(todo):
            print(f"[回補] {i}/{len(todo)} 最近一檔 {ticker} +{added} 筆，累計 +{added_total} 筆", flush=True)

    print(f"[回補] 完成，共新增 {added_total} 筆", flush=True)


if __name__ == "__main__":
    main()
