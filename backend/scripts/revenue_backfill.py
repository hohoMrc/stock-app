"""
月營收歷史回補：從公開資訊觀測站 MOPS t21sc03 逐月抓歷史營收存進 DB。
（官方 OpenAPI 只給最新月，歷史要靠這支）
用法：
  python3 scripts/revenue_backfill.py 2026-01 2026-07   # 回補這個區間（含頭尾）
"""
import sys
import os
import time as _time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))


def _months(start: str, end: str):
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def main():
    if len(sys.argv) != 3:
        print("用法：python3 scripts/revenue_backfill.py 2026-01 2026-07")
        sys.exit(1)
    start, end = sys.argv[1], sys.argv[2]

    from app.db import init_db
    from app.services.revenue_data import fetch_monthly_revenue_mops

    init_db()
    for y, m in _months(start, end):
        try:
            r = fetch_monthly_revenue_mops(y, m)
            print(f"[回補] {r['ym']}：{r['saved']} 筆 "
                  f"（上市 {r['by_market'].get('L', 0)} / 上櫃 {r['by_market'].get('O', 0)}）")
        except Exception as e:
            print(f"[回補] {y}-{m:02d} 失敗：{e}")
        _time.sleep(2)  # 對 MOPS 客氣一點，避免被擋


if __name__ == "__main__":
    main()
