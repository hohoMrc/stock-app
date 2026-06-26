"""
盤後每日 K 線更新腳本
執行時機：台灣時間 15:30（UTC 07:30）
用法：python3 scripts/daily_update.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

from app.db import init_db, get_candles, save_candles
from app.services.stock_data import _fugle_candles, _load_tw_stock_names, _tw_stock_names
from datetime import date, timedelta
import time

init_db()
_load_tw_stock_names()

# 更新對象：DB 裡已有資料的股票 + 常見預設清單
from app.db import _conn

def get_tracked_tickers() -> list[str]:
    with _conn() as conn:
        rows = conn.execute("SELECT DISTINCT ticker FROM candles").fetchall()
    tracked = [r["ticker"] for r in rows]
    # 補上常見股票確保有被追蹤
    defaults = [
        "2330", "2317", "2454", "2412", "2308", "2303", "1301", "1303",
        "2882", "2881", "2891", "2886", "2884", "3711", "2357", "2379",
        "0050", "0056", "00878",
    ]
    for t in defaults:
        if t not in tracked:
            tracked.append(t)
    return tracked


def update_ticker(ticker: str):
    today = date.today()
    from_dt = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    to_dt   = today.strftime("%Y-%m-%d")
    records = _fugle_candles(ticker, from_dt, to_dt)
    if records:
        save_candles(ticker, records)
        print(f"  ✓ {ticker}: {len(records)} 筆")
    else:
        print(f"  - {ticker}: 無資料")


if __name__ == "__main__":
    tickers = get_tracked_tickers()
    print(f"[daily_update] 開始更新 {len(tickers)} 支股票...")
    for t in tickers:
        try:
            update_ticker(t)
        except Exception as e:
            print(f"  ✗ {t}: {e}")
        time.sleep(0.3)  # 避免打爆 Fugle API
    print("[daily_update] 完成")
