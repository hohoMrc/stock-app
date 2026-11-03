"""
月營收更新腳本：抓證交所（上市）/櫃買中心（上櫃）每月營業收入彙總表，存進 DB。
執行時機：營收公布集中在每月 1–10 號，crontab 設那幾天一天多抓幾次。
用法：
  python3 scripts/revenue_update.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import urllib.request, urllib.parse


def _tg_notify(text: str, html: bool = False):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    ids = [i for i in (os.environ.get("TELEGRAM_CHAT_ID"),
                        os.environ.get("TELEGRAM_GROUP_CHAT_ID")) if i]
    for chat_id in ids:
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


def main():
    from app.db import init_db
    from app.services.revenue_data import fetch_monthly_revenue, get_revenue_by_month

    init_db()
    result = fetch_monthly_revenue()
    ym = result["ym"]
    print(f"[營收] {ym} 已更新：{result['saved']} 筆 "
          f"（上市 {result['by_market'].get('L', 0)} / 上櫃 {result['by_market'].get('O', 0)}）")

    if not ym:
        return

    # 年增率前 5 名當通知摘要。排除去年同月營收不到 3 千萬（千元）的分母太小公司，
    # 以及交屋才認列營收的建材營造業——不然榜首全是 +百萬% 的建設公司（跟前端年增榜同規則）
    rows = get_revenue_by_month(ym)
    ranked = sorted(
        (r for r in rows
         if r.get("yoy_pct") is not None and r.get("rev")
         and (r.get("rev_ly") or 0) >= 30000 and r.get("industry") != "建材營造"),
        key=lambda r: r["yoy_pct"], reverse=True,
    )[:5]
    lines = [f"📊 <b>{ym} 月營收已更新</b>（{result['saved']} 檔）", "",
             "年增率前 5 名（排除建材營造、去年同月營收 &lt; 3 千萬）："]
    for r in ranked:
        lines.append(f"・{r['ticker']} {r['name']}　+{r['yoy_pct']:.1f}%")
    _tg_notify("\n".join(lines), html=True)


if __name__ == "__main__":
    main()
