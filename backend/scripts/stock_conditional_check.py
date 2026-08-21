"""
股票模擬下單「智慧單」到價自動買賣檢查
執行時機：台灣時間週一到週五盤中每 2 分鐘（09:00–13:50），跟 alert_price_check.py 同時段
用法：
  python3 scripts/stock_conditional_check.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import urllib.request
import urllib.parse


def _tg_chat_ids() -> list:
    """通知目標：個人 + 群組（TELEGRAM_GROUP_CHAT_ID 未設定時只發個人）。"""
    ids = []
    personal = os.environ.get("TELEGRAM_CHAT_ID")
    group    = os.environ.get("TELEGRAM_GROUP_CHAT_ID")
    if personal:
        ids.append(personal)
    if group:
        ids.append(group)
    return ids


def _tg_notify(text: str, html: bool = False):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    for chat_id in _tg_chat_ids():
        try:
            params = {"chat_id": chat_id, "text": text}
            if html:
                params["parse_mode"] = "HTML"
            payload = urllib.parse.urlencode(params).encode()
            urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/sendMessage", payload, timeout=10
            )
        except Exception as e:
            print(f"[TG] 通知失敗 (chat_id={chat_id}): {e}")


SITE_URL = "https://stock-app-lilac-nine.vercel.app"
SIDE_LABEL = {"buy": "買進", "sell": "賣出"}


def _stock_link(ticker: str) -> str:
    return f'<a href="{SITE_URL}/?ticker={ticker}">{ticker}</a>'


print("[股票智慧單] 開始檢查...")
try:
    from app.services.paper_trading import check_and_execute_conditional_orders

    results = check_and_execute_conditional_orders()
    if not results:
        print("[股票智慧單] 這一輪沒有觸發")
    else:
        for r in results:
            label = f'{_stock_link(r["ticker"])} {SIDE_LABEL[r["side"]]} {r["lots"]}張'
            if r["result"] == "triggered":
                msg = f'🤖 [智慧單成交] {label}　成交價 {r["fill_price"]}'
                if r.get("realized_pl") is not None:
                    msg += f'　已實現損益 {r["realized_pl"]:,.0f}'
            else:
                msg = f'⚠️ [智慧單失敗] {label}　原因：{r["fail_reason"]}'
            print(msg)
            _tg_notify(msg, html=True)
        print(f"[股票智慧單] 這一輪處理 {len(results)} 筆")
except Exception as e:
    print(f"[股票智慧單] 失敗: {e}")

# 這支腳本每2分鐘跑一次，只要查過一次股價就會透過 _get_fugle() 啟動SDK的
# 背景即時連線元件，不主動收尾的話行程會一直不結束
try:
    from app.services.stock_data import shutdown_fugle
    shutdown_fugle()
except Exception as e:
    print(f"[股票智慧單] shutdown_fugle 失敗: {e}")
