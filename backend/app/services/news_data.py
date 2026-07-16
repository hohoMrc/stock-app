"""全市場財經/股市熱門新聞，合併多家來源的官方 RSS（免金鑰、免爬蟲）。"""
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

SOURCES = [
    {"name": "Yahoo股市", "url": "https://tw.stock.yahoo.com/rss?category=news"},
    {"name": "經濟日報",  "url": "https://money.udn.com/rssfeed/news/1001/5588"},
    # ctee.com.tw 自己的網域會擋掉帶 rss/feed 字樣的路徑，改用 Google News 的網域限定搜尋取代
    {"name": "工商時報",  "url": "https://news.google.com/rss/search?q=site:ctee.com.tw&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"},
]

_cache: dict = {}   # "news" → (查詢時間, list)
_CACHE_TTL = 600     # 10 分鐘快取，避免短時間內重複抓


def _fetch_source(source: dict) -> list[dict]:
    try:
        resp = requests.get(source["url"], timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            pub   = (item.findtext("pubDate") or "").strip()
            if not title or not link:
                continue
            items.append({"title": title, "link": link, "pub_date": pub, "source": source["name"]})
        return items
    except Exception as e:
        print(f"[news] {source['name']} RSS 失敗: {e}")
        return []


def _parse_pubdate(pub: str):
    try:
        return parsedate_to_datetime(pub)
    except Exception:
        return None


def get_hot_news(limit: int = 20) -> list[dict]:
    """抓多家來源的財經新聞 RSS，依發布時間排序（新到舊）合併回傳。"""
    cached = _cache.get("news")
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1][:limit]

    all_items = []
    for source in SOURCES:
        all_items.extend(_fetch_source(source))

    if not all_items:
        return cached[1][:limit] if cached else []

    epoch = datetime.min.replace(tzinfo=timezone.utc)
    all_items.sort(key=lambda n: _parse_pubdate(n["pub_date"]) or epoch, reverse=True)

    _cache["news"] = (time.time(), all_items)
    return all_items[:limit]
