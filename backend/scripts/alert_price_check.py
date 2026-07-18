"""
個人化到價提醒檢查
執行時機：台灣時間週一到週五盤中每 2 分鐘（09:00–13:50）
用法：
  python3 scripts/alert_price_check.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import urllib.request
import urllib.parse

SITE_URL = "https://stock-app-lilac-nine.vercel.app"


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


def _stock_link(ticker: str, name: str) -> str:
    return f'<a href="{SITE_URL}/?ticker={ticker}">{ticker} {name}</a>'


print("[到價提醒] 開始檢查...")
try:
    from app.db import get_active_price_alerts, mark_alert_triggered
    from app.services.stock_data import get_watchlist_quotes

    active_alerts = get_active_price_alerts()
    if not active_alerts:
        print("[到價提醒] 目前無啟用中的提醒")
    else:
        tickers = sorted({a["ticker"] for a in active_alerts})
        quotes = {q["ticker"]: q for q in get_watchlist_quotes(tickers)}

        triggered = 0
        for alert in active_alerts:
            q = quotes.get(alert["ticker"])
            close = q.get("close") if q else None
            if close is None:
                continue

            target = alert["target_price"]
            hit = (
                (alert["alert_type"] == "price_above" and close >= target) or
                (alert["alert_type"] == "price_below" and close <= target)
            )
            if not hit:
                continue

            cmp_label = "≥" if alert["alert_type"] == "price_above" else "≤"
            name = q.get("name", "")
            msg = (
                f'🔔 [價格提醒] {_stock_link(alert["ticker"], name)}　'
                f'現價 {close} 元，已達 {cmp_label} {target} 元'
            )
            print(msg)
            _tg_notify(msg, html=True)
            mark_alert_triggered(alert["id"])
            triggered += 1

        print(f"[到價提醒] 檢查 {len(active_alerts)} 筆，觸發 {triggered} 筆")
except Exception as e:
    print(f"[到價提醒] 失敗: {e}")
