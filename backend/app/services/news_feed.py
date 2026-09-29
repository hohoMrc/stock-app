"""大盤狀態頁「盤前快訊」「今日焦點」的新聞來源。

只使用中央社（CNA）官方公開 RSS（財經／政治／國際），未串接鉅亨網等其他來源——
鉅亨網目前查不到穩定可用的公開 RSS 端點，之後如果找到可再加進 CNA_FEEDS。
"""
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

TW_TZ = ZoneInfo("Asia/Taipei")

CNA_FEEDS = [
    ("財經", "https://feeds.feedburner.com/rsscna/finance"),
    ("政策", "https://feeds.feedburner.com/rsscna/politics"),
    ("國際", "https://feeds.feedburner.com/rsscna/intworld"),
]

NEWS_TTL = 600  # 10分鐘快取，避免每次開頁都打中央社

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


def _get_all_cna_items(force: bool = False) -> list:
    if not force:
        cached = _cache_get("cna_all", NEWS_TTL)
        if cached is not None:
            return cached

    all_items = []
    for category, url in CNA_FEEDS:
        all_items.extend(_fetch_feed_items(category, url))
    all_items.sort(key=lambda x: x["_dt"], reverse=True)
    _cache_set("cna_all", all_items)
    return all_items


def get_premarket_news(limit: int = 15, force: bool = False) -> list:
    """最新財經/政策/國際新聞，供大盤狀態頁「盤前快訊」使用。"""
    items = _get_all_cna_items(force)
    return [{k: v for k, v in it.items() if k != "_dt"} for it in items[:limit]]


def get_today_focus(limit: int = 10, force: bool = False) -> list:
    """台北時間今天發布的新聞，依時間新到舊，供「今日焦點」使用。"""
    items = _get_all_cna_items(force)
    today_tw = datetime.now(TW_TZ).date()
    todays = [it for it in items if it["_dt"].astimezone(TW_TZ).date() == today_tw]
    return [{k: v for k, v in it.items() if k != "_dt"} for it in todays[:limit]]
