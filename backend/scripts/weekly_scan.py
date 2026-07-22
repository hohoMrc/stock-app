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
        print("[TG] 未設定 TELEGRAM_BOT_TOKEN")
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

def _stock_link(ticker: str, name: str, extra: str = "") -> str:
    url = f"{SITE_URL}/?ticker={ticker}"
    return f'<a href="{url}">{ticker} {name}</a>{extra}'


if __name__ == "__main__":
    from app.db import init_db
    init_db()

    print("[週漲幅] 開始掃描...")
    try:
        from app.services.stock_data import scan_all_weekly_surge
        from app.services.signal_tracking import record_signals
        hits = scan_all_weekly_surge(min_weekly_change=20, min_volume=1000, min_capital=2)
        record_signals("weekly_surge", hits)

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

    print("[篩選成效週報] 彙整近90天各快篩表現...")
    try:
        from app.services.signal_tracking import get_performance_summary
        summary = get_performance_summary(90)
        if summary:
            lines = [
                f'{s["label"]}：{s["count"]} 次訊號，20日勝率 {s["win_rate"]}%，'
                f'平均報酬 5日{s["avg_return_5d"]}% / 10日{s["avg_return_10d"]}% / 20日{s["avg_return_20d"]}%'
                for s in summary
            ]
            msg = "[篩選成效週報] 近90天各快篩表現（20日報酬率已可完整評估的訊號）\n" + "\n".join(lines)
        else:
            msg = "[篩選成效週報] 資料還不夠（訊號日需滿20個交易日才會納入統計），累積數週後再看"
        print(msg)
        _tg_notify(msg)
    except Exception as e:
        print(f"[篩選成效週報] 失敗: {e}")
