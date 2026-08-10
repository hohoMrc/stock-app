"""全市場財經/股市熱門新聞，合併多家來源的官方 RSS（免金鑰、免爬蟲）。"""
import time
import difflib
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


HOT_SIM_THRESHOLD = 0.55   # 標題相似度門檻（difflib ratio，0~1）
HOT_WINDOW_HOURS = 12      # 只把發布時間相近的報導視為同一則事件，避免不同天的類似標題誤判


def _cluster_hot_scores(items: list[dict]) -> list[int]:
    """免費 RSS 沒有現成的熱度欄位，用「有幾家不同來源在差不多時間報同一則新聞」當替代訊號：
    標題相似度夠高 + 發布時間夠接近 → 視為同一則事件，事件涵蓋的不同來源數就是熱度分數。
    同一家來源自己重複發文不算數（只看跨來源）。
    """
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    dates = [_parse_pubdate(it["pub_date"]) for it in items]
    for i in range(n):
        for j in range(i + 1, n):
            if items[i]["source"] == items[j]["source"]:
                continue
            if dates[i] and dates[j]:
                delta_hours = abs((dates[i] - dates[j]).total_seconds()) / 3600
                if delta_hours > HOT_WINDOW_HOURS:
                    continue
            if difflib.SequenceMatcher(None, items[i]["title"], items[j]["title"]).ratio() >= HOT_SIM_THRESHOLD:
                union(i, j)

    cluster_sources: dict[int, set] = {}
    for i in range(n):
        root = find(i)
        cluster_sources.setdefault(root, set()).add(items[i]["source"])

    return [len(cluster_sources[find(i)]) for i in range(n)]


def get_hot_news(limit: int = 20) -> list[dict]:
    """抓多家來源的財經新聞 RSS，先依發布時間排序（新到舊），
    再依「熱度」（多家來源報同一則事件）做一次穩定排序拉到前面，
    熱度相同的新聞維持原本的時間新到舊順序。"""
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

    hot_scores = _cluster_hot_scores(all_items)
    for item, score in zip(all_items, hot_scores):
        item["hot_score"] = score
    all_items.sort(key=lambda n: n["hot_score"], reverse=True)

    _cache["news"] = (time.time(), all_items)
    return all_items[:limit]
