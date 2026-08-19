"""
每日熱門財經新聞 TG 通知
執行時機：台灣時間每日 07:30（UTC 前一日 23:30），開盤前發送，確保新聞夠新
用法：
  python3 scripts/news_update.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import re
import html
import urllib.request
import urllib.parse


def _md_bold_to_html(text: str) -> str:
    """AI 摘要用 **粗體** 的 markdown 語法，但 TG 訊息是純文字模式送的不會被解析，
    改成先跳脫 HTML 特殊字元、再把 **文字** 轉成 <b>文字</b>，訊息改用 HTML 模式送。"""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text))


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


TG_MAX_LEN = 3900  # Telegram 單則訊息上限 4096 字元，留點安全邊界


def _tg_notify_lines(title: str, lines: list[str], empty_text: str):
    """依 Telegram 4096 字元上限自動分段發送，避免新聞數太多導致單則訊息過長被拒（HTTP 400）。"""
    if not lines:
        print(empty_text)
        _tg_notify(empty_text, html=True)
        return

    chunks, cur, cur_len = [], [], 0
    for line in lines:
        if cur and cur_len + len(line) + 1 > TG_MAX_LEN:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        chunks.append(cur)

    for i, chunk in enumerate(chunks):
        header = title if i == 0 else f"{title}（續 {i + 1}/{len(chunks)}）"
        msg = header + "\n" + "\n".join(chunk)
        print(msg)
        _tg_notify(msg, html=True)


print("[熱門新聞] 抓取財經新聞...")
try:
    from app.services.news_data import get_hot_news
    news = get_hot_news(30)

    # 台股觀察（從新聞自帶的關聯個股直接產生，不用AI）跟AI摘要分開處理，
    # 這樣即使Groq那邊出問題（額度、模型下架等），台股觀察還是能正常更新，
    # 不會因為AI那段失敗就整個台股觀察也一起卡住不更新。
    if news:
        from datetime import date
        from app.services.news_summary import build_stock_watch
        from app.db import init_db, save_news_summary

        init_db()
        stock_watch = build_stock_watch(news)
        today_str = date.today().strftime("%Y-%m-%d")

        summary_text = None
        try:
            from app.services.news_summary import summarize_news
            summary_text = summarize_news(news)
        except Exception as e:
            print(f"[熱門新聞] AI摘要失敗: {e}")
            summary_text = "（AI摘要暫時無法產生，以下為台股觀察個股清單）"

        save_news_summary(today_str, summary_text, stock_watch)

        watch_lines = [
            f'{"🔥" if s["tag"] == "熱門股" else ""}<b>{html.escape(s["name"])}({s["code"]})</b>：{html.escape(s["headline"])}'
            for s in stock_watch
        ]
        msg = (
            f"📰 <b>今日新聞重點</b>\n\n{_md_bold_to_html(summary_text[:2500])}"
            f"\n\n📈 <b>台股觀察</b>\n" + "\n".join(watch_lines[:15])
        )
        print(msg)
        _tg_notify(msg[:3900], html=True)

    lines = [f'<a href="{n["link"]}">{n["title"]}</a>' for n in news[:15]]
    _tg_notify_lines(
        f"[熱門新聞] 今日財經新聞 Top {len(lines)}",
        lines,
        "[熱門新聞] 抓取失敗，暫無新聞",
    )
except Exception as e:
    print(f"[熱門新聞] 失敗: {e}")
