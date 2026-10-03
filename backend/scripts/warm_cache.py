"""
背景預熱大盤狀態頁會用到的全市場掃描/排行快取，讓使用者打開頁面時
永遠只會命中已經算好的快取，不會卡到冷啟動（全市場技術指標掃描單次要
20秒以上）。這幾個函式都用 RANKING_TTL=300秒(5分鐘) 的快取，所以排程
抓每 4 分鐘跑一次，確保快取隨時是熱的。

注意：必須直接打本機正在跑的服務（localhost:8000），不能用 import
直接呼叫 stock_data.py 的函式——那樣會在「這支排程腳本自己的 process」
裡算好快取，跟真正在跑、服務使用者的 uvicorn process 是不同的記憶體
空間，兩邊的 _ranking_cache 字典互不相通，獨立呼叫完全沒有預熱到
使用者實際會打到的那份快取。

執行時機：建議台灣時間每天白天到晚上每 4 分鐘跑一次（涵蓋盤中+夜盤）。
用法：
  python3 scripts/warm_cache.py
"""
import requests

BASE = "http://localhost:8000"

ENDPOINTS = [
    ("大盤總覽（含全市場掃描/排行/期貨）", "/api/market/overview"),
    ("週轉率排行",                      "/api/stocks/ranking/turnover?limit=50"),
    ("成交值排行",                      "/api/stocks/ranking/trade-value?limit=50"),
]

if __name__ == "__main__":
    for name, path in ENDPOINTS:
        try:
            resp = requests.get(f"{BASE}{path}", timeout=60)
            print(f"[預熱快取] {name}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"[預熱快取] {name} 失敗: {e}")
