"""全市場財經/股市熱門新聞（Yahoo股市官方 RSS，免金鑰、免爬蟲）。"""
import time
import requests
import xml.etree.ElementTree as ET

YAHOO_NEWS_RSS = "https://tw.stock.yahoo.com/rss?category=news"

_cache: dict = {}   # "news" → (查詢時間, list)
_CACHE_TTL = 600     # 10 分鐘快取，避免短時間內重複抓


def get_hot_news(limit: int = 20) -> list[dict]:
    """抓 Yahoo股市財經新聞 RSS，回傳熱門新聞清單（依 RSS 原始順序，越前面越新）。"""
    cached = _cache.get("news")
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1][:limit]

    try:
        resp = requests.get(
            YAHOO_NEWS_RSS, timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            pub   = (item.findtext("pubDate") or "").strip()
            if not title or not link:
                continue
            items.append({"title": title, "link": link, "pub_date": pub})
        _cache["news"] = (time.time(), items)
        return items[:limit]
    except Exception as e:
        print(f"[news] Yahoo股市 RSS 失敗: {e}")
        return cached[1][:limit] if cached else []
