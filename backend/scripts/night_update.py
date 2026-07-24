"""
台指期/微型台指 夜盤 K 線存檔腳本
執行時機：台灣時間每日 05:30（UTC 21:30 前一天），夜盤 15:00–隔日05:00 收盤後跑，
確保抓到的是完整的一整段夜盤（跟日盤共用同一張 futures_candles 表、同一個 product key，
時間本來就不重疊，天然接續成連續走勢）。
用法：
  python3 scripts/night_update.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import datetime as _dt

from app.db import init_db, save_futures_candles
from app.services.futures_data import _current_symbol, _get_client, shutdown_sdk, TZ_TAIPEI

init_db()

for product in ["TXF", "TMF"]:
    symbol = _current_symbol(product)
    for tf in ["1", "5", "15", "30", "60"]:
        try:
            data = _get_client().futopt.intraday.candles(symbol=symbol, timeframe=tf, session="afterhours")
            candles = []
            for c in data.get("data", []):
                raw_dt = _dt.datetime.fromisoformat(c["date"])
                if raw_dt.tzinfo is None:
                    raw_dt = raw_dt.replace(tzinfo=TZ_TAIPEI)
                candles.append({
                    "time":   int(raw_dt.timestamp()),
                    "open":   c["open"],
                    "high":   c["high"],
                    "low":    c["low"],
                    "close":  c["close"],
                    "volume": c.get("volume", 0),
                })
            if candles:
                save_futures_candles(product, tf, candles)
                print(f"[夜盤K線] {product} {tf}min: 存入 {len(candles)} 根")
            else:
                print(f"[夜盤K線] {product} {tf}min: 無資料（可能無夜盤，如週末）")
        except Exception as e:
            print(f"[夜盤K線] {product} {tf}min 失敗: {e}")

# SDK 的 init_realtime() 會啟動背景連線元件，短命腳本結束前要主動收尾，
# 不然直譯器關閉時背景執行緒還活著會噴 Fatal Python error（gilstate_tss_set）。
try:
    shutdown_sdk()
except Exception as e:
    print(f"[futures] shutdown_sdk 失敗: {e}")
