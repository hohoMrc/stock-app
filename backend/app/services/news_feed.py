"""大盤狀態頁「盤前快訊」「今日焦點」的新聞來源。

合併兩個來源：
- 中央社（CNA）官方公開 RSS（財經／政治／國際）
- 鉅亨網（cnyes）新聞 API（`app.services.news_data.get_hot_news`，跟每天早上
  07:30 TG 熱門新聞用的是同一支，自帶分類標籤如〈熱門股〉〈台股盤前要聞〉、
  品質比純 RSS 標題好）
"""
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

from app.services.news_data import get_hot_news

TW_TZ = ZoneInfo("Asia/Taipei")

CNA_FEEDS = [
    ("財經", "https://feeds.feedburner.com/rsscna/finance"),
    ("政策", "https://feeds.feedburner.com/rsscna/politics"),
    ("國際", "https://feeds.feedburner.com/rsscna/intworld"),
]

NEWS_TTL = 600  # 10分鐘快取，避免每次開頁都打外部新聞來源

_news_cache: dict = {}


def _cache_get(key, ttl):
    entry = _news_cache.get(key)
    if entry and time.time() - entry[0] < ttl:
        return entry[1]
    return None


def _cache_set(key, value):
    _news_cache[key] = (time.time(), value)


def _fetch_feed_items(category: str, url: str) -> list:
    items = []
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if not title or not link or not pub:
                continue
            try:
                dt = parsedate_to_datetime(pub)
            except Exception:
                continue
            items.append({
                "category": category,
                "title": title,
                "link": link,
                "source": "中央社",
                "published_at": dt.astimezone(TW_TZ).isoformat(),
                "_dt": dt,
            })
    except Exception as e:
        print(f"[CNA RSS] {category} 抓取失敗: {e}")
    return items


def _fetch_cnyes_items() -> list:
    items = []
    try:
        for n in get_hot_news(30):
            pub_date = n.get("pub_date")
            title = n.get("title")
            link = n.get("link")
            if not pub_date or not title or not link:
                continue
            try:
                dt = datetime.fromisoformat(pub_date)
            except Exception:
                continue
            items.append({
                "category": n.get("tag") or "鉅亨網",
                "title": title,
                "link": link,
                "source": "鉅亨網",
                "published_at": dt.astimezone(TW_TZ).isoformat(),
                "_dt": dt,
            })
    except Exception as e:
        print(f"[news] 鉅亨網抓取失敗: {e}")
    return items


def _get_all_news_items(force: bool = False) -> list:
    if not force:
        cached = _cache_get("all_news", NEWS_TTL)
        if cached is not None:
            return cached

    all_items = []
    for category, url in CNA_FEEDS:
        all_items.extend(_fetch_feed_items(category, url))
    all_items.extend(_fetch_cnyes_items())

    # 同一篇報導可能同時出現在中央社多個分類 feed、或兩邊來源剛好都報導同一則，
    # 依 link 去重（兩個來源的 link 網域本來就不同，只會擋到同來源內部的重複）
    seen_links: set = set()
    deduped = []
    for it in all_items:
        if it["link"] in seen_links:
            continue
        seen_links.add(it["link"])
        deduped.append(it)

    deduped.sort(key=lambda x: x["_dt"], reverse=True)
    _cache_set("all_news", deduped)
    return deduped


def get_premarket_news(limit: int = 15, force: bool = False) -> list:
    """最新財經/政策/國際新聞，供大盤狀態頁「盤前快訊」使用。"""
    items = _get_all_news_items(force)
    return [{k: v for k, v in it.items() if k != "_dt"} for it in items[:limit]]


def get_today_focus(limit: int = 10, force: bool = False) -> list:
    """台北時間今天發布的新聞，依時間新到舊，供「今日焦點」使用。"""
    items = _get_all_news_items(force)
    today_tw = datetime.now(TW_TZ).date()
    todays = [it for it in items if it["_dt"].astimezone(TW_TZ).date() == today_tw]
    return [{k: v for k, v in it.items() if k != "_dt"} for it in todays[:limit]]
