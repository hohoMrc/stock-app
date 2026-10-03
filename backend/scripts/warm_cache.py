"""
背景預熱大盤狀態頁會用到的全市場掃描/排行快取，讓使用者打開頁面時
永遠只會命中已經算好的快取，不會卡到冷啟動（全市場技術指標掃描單次要
20秒以上）。這幾個函式都用 RANKING_TTL=300秒(5分鐘) 的快取，所以排程
抓每 4 分鐘跑一次，確保快取隨時是熱的。

執行時機：建議台灣時間每天白天到晚上每 4 分鐘跑一次（涵蓋盤中+夜盤）。
用法：
  python3 scripts/warm_cache.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

from app.services.stock_data import (
    get_taiex_quote, get_market_breadth, get_institutional_summary,
    get_industry_performance, get_movers_ranking,
    scan_ma_squeeze, scan_near_ema60, scan_volume_breakout, scan_institutional_buying,
    get_turnover_ranking, get_trade_value_ranking,
)
from app.services.futures_data import get_futures_quote, get_institutional_positions

TASKS = [
    ("大盤指數",     get_taiex_quote),
    ("漲跌家數",     get_market_breadth),
    ("三大法人",     get_institutional_summary),
    ("產業表現",     get_industry_performance),
    ("漲幅王",       lambda: get_movers_ranking("up", 5)),
    ("跌幅王",       lambda: get_movers_ranking("down", 5)),
    ("鳥嘴與分歧",   lambda: scan_ma_squeeze(500)),
    ("EMA60近線",    lambda: scan_near_ema60(500)),
    ("量價突破",     lambda: scan_volume_breakout(500)),
    ("法人連買",     lambda: scan_institutional_buying(3, 500, 2000)),
    ("台指期報價",   get_futures_quote),
    ("期貨法人部位", get_institutional_positions),
    ("週轉率排行",   lambda: get_turnover_ranking(50)),
    ("成交值排行",   lambda: get_trade_value_ranking(50)),
]

if __name__ == "__main__":
    for name, fn in TASKS:
        try:
            fn()
        except Exception as e:
            print(f"[預熱快取] {name} 失敗: {e}")
