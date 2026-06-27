"""
盤後每日 K 線更新腳本
執行時機：台灣時間 15:30（UTC 07:30）
用法：
  python3 scripts/daily_update.py          # 更新最近 7 天
  python3 scripts/daily_update.py --full   # 首次回填 3 個月（較慢，約 10 分鐘）
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

from app.db import init_db, save_candles, _conn
from app.services.stock_data import _fugle_candles, _load_tw_stock_names, _tw_stock_names
from datetime import date, timedelta
import time

init_db()
_load_tw_stock_names()

FULL_MODE = "--full" in sys.argv


def get_all_tickers() -> list[str]:
    """回傳所有要更新的代號：TWSE 完整清單 + 上櫃常見股。"""
    tickers = list(_tw_stock_names.keys())
    # 補上不在 TWSE 清單的 ETF / 上櫃股
    extras = ["0056", "00878", "006208", "00881", "00713", "00900", "4904", "3045"]
    for t in extras:
        if t not in tickers:
            tickers.append(t)
    return tickers


def update_ticker(ticker: str, days: int = 7):
    today   = date.today()
    from_dt = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    to_dt   = today.strftime("%Y-%m-%d")
    records = _fugle_candles(ticker, from_dt, to_dt)
    if records:
        save_candles(ticker, records)
        return len(records)
    return 0


if __name__ == "__main__":
    tickers = get_all_tickers()
    days    = 90 if FULL_MODE else 7
    mode    = "回填 3 個月" if FULL_MODE else "更新 7 天"

    print(f"[daily_update] {mode}，共 {len(tickers)} 支股票...")
    ok = fail = skip = 0

    for i, t in enumerate(tickers, 1):
        try:
            n = update_ticker(t, days)
            if n:
                ok += 1
                if FULL_MODE and i % 50 == 0:
                    print(f"  進度 {i}/{len(tickers)} ...")
            else:
                skip += 1
        except Exception as e:
            print(f"  ✗ {t}: {e}")
            fail += 1
        time.sleep(0.3)

    print(f"[daily_update] 完成：成功 {ok}，無資料 {skip}，失敗 {fail}")
