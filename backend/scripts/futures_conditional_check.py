"""
期貨模擬下單「智慧單」到價自動下單檢查
執行時機：期貨日盤+夜盤交易時段每 2 分鐘（08:00-13:59、15:00-23:59、00:00-05:59）
用法：
  python3 scripts/futures_conditional_check.py
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


PRODUCT_LABEL = {"TXF": "大台指", "TMF": "微台指"}
SIDE_LABEL = {"buy": "買進", "sell": "賣出"}

print("[期貨智慧單] 開始檢查...")
try:
    from app.services.paper_futures import check_and_execute_conditional_orders

    results = check_and_execute_conditional_orders()
    if not results:
        print("[期貨智慧單] 這一輪沒有觸發")
    else:
        for r in results:
            label = f'{PRODUCT_LABEL[r["product"]]} {SIDE_LABEL[r["side"]]} {r["qty"]}口'
            if r["result"] == "triggered":
                detail_parts = []
                if r.get("closed_qty"):
                    detail_parts.append(f'平倉{r["closed_qty"]}口')
                if r.get("opened_qty"):
                    detail_parts.append(f'開倉{r["opened_qty"]}口')
                msg = f'🤖 [智慧單成交] {label}　成交價 {r["fill_price"]}'
                if detail_parts:
                    msg += "　" + "，".join(detail_parts)
                if r.get("realized_pl") is not None:
                    msg += f'　已實現損益 {r["realized_pl"]:,.0f}'
            else:
                msg = f'⚠️ [智慧單失敗] {label}　原因：{r["fail_reason"]}'
            print(msg)
            _tg_notify(msg)
        print(f"[期貨智慧單] 這一輪處理 {len(results)} 筆")
except Exception as e:
    print(f"[期貨智慧單] 失敗: {e}")
