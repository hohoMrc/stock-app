"""
Claude 當沖模擬帳戶：盤中進出場檢查
執行時機：台灣時間週一到週五盤中每 2 分鐘（09:00–13:50），跟 stock_conditional_check.py 同時段
用法：
  python3 scripts/day_trading_check.py
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


def _stock_link(ticker: str) -> str:
    return f'<a href="{SITE_URL}/?ticker={ticker}">{ticker}</a>'


print("[Claude當沖] 開始檢查...")
try:
    from app.services.claude_trader import run_day_trading_check

    result = run_day_trading_check()
    exits, entries = result["exits"], result["entries"]

    for x in exits:
        pl_note = f'　已實現損益 {x["realized_pl"]:,.0f}' if x.get("realized_pl") is not None else ""
        msg = f'🤖 [Claude當沖出場] {_stock_link(x["ticker"])} {x.get("name","")}　{x["reason"]}{pl_note}'
        print(msg)
        _tg_notify(msg, html=True)

    for e in entries:
        msg = f'🤖 [Claude當沖進場] {_stock_link(e["ticker"])} {e.get("name","")}　{e["lots"]}張 @ {e["price"]}　{e["reason"]}'
        print(msg)
        _tg_notify(msg, html=True)

    print(f"[Claude當沖] 這一輪出場 {len(exits)} 筆、進場 {len(entries)} 筆")
except Exception as e:
    print(f"[Claude當沖] 失敗: {e}")

# 這支腳本每2分鐘跑一次，只要查過一次股價就會透過 _get_fugle() 啟動SDK的
# 背景即時連線元件，不主動收尾的話行程會一直不結束
try:
    from app.services.stock_data import shutdown_fugle
    shutdown_fugle()
except Exception as e:
    print(f"[Claude當沖] shutdown_fugle 失敗: {e}")
