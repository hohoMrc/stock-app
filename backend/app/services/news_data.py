"""台股新聞，改用鉅亨網（cnyes）的新聞列表 API。

原本合併 Yahoo股市/經濟日報/工商時報三家 RSS，用標題相似度比對「熱度」。改用鉅亨網後
不需要那套了：鉅亨網自己會在文章附上結構化的關聯個股（market 欄位），還有現成的分類
標籤（〈熱門股〉〈台股盤前要聞〉「營收速報」等），資料品質跟顆粒度都比 RSS 標題好。

這支 API（api.cnyes.com/media/api/v1/newslist/category/...）是鉅亨網自己 App/網站在用的
內部介面，沒有官方文件，格式未來可能會改版；讀取量小、唯讀，個人使用風險可接受。
"""
import re
import time
import requests
from datetime import datetime, timezone

CNYES_API = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock_news"
CNYES_ARTICLE_URL = "https://news.cnyes.com/news/id/{news_id}"

_cache: dict = {}   # "news" → (查詢時間, list)
_CACHE_TTL = 600     # 10 分鐘快取，避免短時間內重複抓

# 標題常見的分類標籤：〈熱門股〉〈台股盤前要聞〉這種帶括號的，或「營收速報 - 」「盤中速報 - 」
# 這種不帶括號、後面接「 - 」的
_TAG_BRACKET_RE = re.compile(r'^[〈\[]([^〉\]]{1,10})[〉\]]')
_TAG_PLAIN_RE   = re.compile(r'^([一-鿿]{2,6})\s*-\s*')


def _extract_tag(title: str) -> str | None:
    m = _TAG_BRACKET_RE.match(title)
    if m:
        return m.group(1)
    m = _TAG_PLAIN_RE.match(title)
    if m:
        return m.group(1)
    return None


def _fetch_cnyes(limit: int = 30) -> list[dict]:
    try:
        resp = requests.get(
            CNYES_API, params={"limit": min(limit, 30)}, timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        items = []
        for it in data.get("items", {}).get("data", []):
            title = (it.get("title") or "").strip()
            news_id = it.get("newsId")
            if not title or not news_id:
                continue
            pub_at = it.get("publishAt")
            pub_iso = (
                datetime.fromtimestamp(pub_at, tz=timezone.utc).isoformat()
                if pub_at else None
            )
            stocks = [
                {"code": m["code"], "name": m["name"]}
                for m in (it.get("market") or []) if m.get("code") and m.get("name")
            ]
            items.append({
                "title":    title,
                "link":     CNYES_ARTICLE_URL.format(news_id=news_id),
                "pub_date": pub_iso,
                "source":   "鉅亨網",
                "tag":      _extract_tag(title),
                "stocks":   stocks,
                "_pub_at":  pub_at or 0,
            })
        return items
    except Exception as e:
        print(f"[news] 鉅亨網 API 失敗: {e}")
        return []


def get_hot_news(limit: int = 20) -> list[dict]:
    """抓鉅亨網台股新聞，依發布時間排序（新到舊）回傳。"""
    cached = _cache.get("news")
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1][:limit]

    items = _fetch_cnyes(max(limit, 30))
    if not items:
        return cached[1][:limit] if cached else []

    items.sort(key=lambda n: n["_pub_at"], reverse=True)
    for it in items:
        it.pop("_pub_at", None)

    _cache["news"] = (time.time(), items)
    return items[:limit]
