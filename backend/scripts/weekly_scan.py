"""
每週六盤後週漲幅掃描
執行時機：台灣時間週六 09:00（UTC 01:00）
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import urllib.request
import urllib.parse


SITE_URL = "https://stock-app-lilac-nine.vercel.app"

def _tg_notify(text: str, html: bool = False):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[TG] 未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return
    try:
        params = {"chat_id": chat_id, "text": text}
        if html:
            params["parse_mode"] = "HTML"
        payload = urllib.parse.urlencode(params).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", payload, timeout=10
        )
    except Exception as e:
        print(f"[TG] 通知失敗: {e}")

def _stock_link(ticker: str, name: str, extra: str = "") -> str:
    url = f"{SITE_URL}/?ticker={ticker}"
    return f'<a href="{url}">{ticker} {name}</a>{extra}'


if __name__ == "__main__":
    from app.db import init_db
    init_db()

    print("[週漲幅] 開始掃描...")
    try:
        from app.services.stock_data import scan_all_weekly_surge
        hits = scan_all_weekly_surge(min_weekly_change=20, min_volume=1000, min_capital=2)

        if hits:
            lines = [
                _stock_link(
                    s["ticker"], s.get("name", ""),
                    f"  週漲 +{s.get('weekly_change_pct', '')}%  {s.get('price', '')}元"
                )
                for s in hits
            ]
            msg = f"[週漲幅] 本週找到 {len(hits)} 支（週漲≥20%、日量≥1000張）\n" + "\n".join(lines)
        else:
            msg = "[週漲幅] 本週無符合條件的股票（週漲≥20%、日量≥1000張）"

        print(msg)
        _tg_notify(msg, html=True)
    except Exception as e:
        err = f"[週漲幅] 掃描失敗: {e}"
        print(err)
        _tg_notify(err)
