"""月營收資料：抓取證交所（上市）/櫃買中心（上櫃）每月營業收入彙總表，
存進 DB，並組成佈告欄需要的榜單資料。

資料來源（官方 OpenAPI，免費、已含成長率）：
- 上市：https://openapi.twse.com.tw/v1/opendata/t187ap05_L
- 上櫃：https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O
         （走 _tpex_get 放寬 SSL，見 stock_data._tpex_get 的說明）
"""
import re
import time

import requests

from app.services.stock_data import _tpex_get, _TWSE_HEADERS
from app.db import (
    bulk_save_monthly_revenue,
    get_revenue_months,
    get_revenue_by_month,
    get_ticker_revenue_history,
)

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"

# 官方欄位名 → 我們的欄位名
_FIELD_MAP = {
    "公司代號": "ticker",
    "公司名稱": "name",
    "產業別": "industry",
    "營業收入-當月營收": "rev",
    "營業收入-上月營收": "rev_prev",
    "營業收入-去年當月營收": "rev_ly",
    "營業收入-上月比較增減(%)": "mom_pct",
    "營業收入-去年同月增減(%)": "yoy_pct",
    "累計營業收入-當月累計營收": "cum",
    "累計營業收入-去年累計營收": "cum_ly",
    "累計營業收入-前期比較增減(%)": "cum_yoy_pct",
    "備註": "memo",
}
_INT_FIELDS = ("rev", "rev_prev", "rev_ly", "cum", "cum_ly")
_FLOAT_FIELDS = ("mom_pct", "yoy_pct", "cum_yoy_pct")

_board_cache: dict = {}
BOARD_TTL = 300  # 佈告欄資料快取 5 分鐘


def _roc_ym_to_western(roc_ym: str) -> str | None:
    """民國年月（如 '11508'）→ 西元 '2026-08'。"""
    s = str(roc_ym).strip()
    if len(s) < 5:
        return None
    year = int(s[:3]) + 1911
    month = int(s[3:5])
    return f"{year}-{month:02d}"


def _num(val, is_int: bool):
    if val in (None, "", "-"):
        return None
    try:
        return int(float(val)) if is_int else round(float(val), 2)
    except (ValueError, TypeError):
        return None


def _parse_rows(raw: list, market: str) -> list[dict]:
    out = []
    for item in raw:
        ym = _roc_ym_to_western(item.get("資料年月", ""))
        ticker = str(item.get("公司代號", "")).strip()
        if not ym or not ticker:
            continue
        rec = {"ym": ym, "market": market}
        for src, dst in _FIELD_MAP.items():
            v = item.get(src)
            if dst in _INT_FIELDS:
                rec[dst] = _num(v, True)
            elif dst in _FLOAT_FIELDS:
                rec[dst] = _num(v, False)
            else:
                rec[dst] = (str(v).strip() if v not in (None, "") else None)
        out.append(rec)
    return out


def fetch_monthly_revenue() -> dict:
    """抓上市 + 上櫃最新月營收並存進 DB。回傳 {ym, saved, by_market}。"""
    records: list[dict] = []
    by_market = {}

    # 上市（TWSE）
    resp = requests.get(TWSE_URL, headers=_TWSE_HEADERS, timeout=20)
    resp.raise_for_status()
    rows_l = _parse_rows(resp.json(), "L")
    records += rows_l
    by_market["L"] = len(rows_l)

    # 上櫃（TPEx，放寬 SSL）
    resp = _tpex_get(TPEX_URL, headers=_TWSE_HEADERS, timeout=20)
    resp.raise_for_status()
    rows_o = _parse_rows(resp.json(), "O")
    records += rows_o
    by_market["O"] = len(rows_o)

    saved = bulk_save_monthly_revenue(records)
    ym = records[0]["ym"] if records else None
    _board_cache.clear()  # 有新資料，清快取
    return {"ym": ym, "saved": saved, "by_market": by_market}


# ── 歷史回補：公開資訊觀測站 MOPS t21sc03 逐月彙總表 ──────────
# 官方 OpenAPI 只給最新月，歷史要抓 MOPS 的月報表（big5 編碼的 HTML table）。
# 個股資料列欄位：代號, 名稱, 當月營收, 上月營收, 去年當月, 月增%, 當月累計,
#                 去年累計, 累計年增%, 備註
#（注意：個股列「沒有」去年同月增減(%)，只有合計列才有，所以 yoy 自己用營收算）
MOPS_URL = "https://mopsov.twse.com.tw/nas/t21/{seg}/t21sc03_{roc}_{month}_0.html"
_MOPS_SEG = {"L": "sii", "O": "otc"}

_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _cell_text(html: str) -> str:
    return _TAG_RE.sub("", html).replace("&nbsp;", "").replace("　", "").strip()


def _parse_mops(html: str, ym: str, market: str) -> list[dict]:
    out = []
    industry = None
    for tr in _TR_RE.findall(html):
        if "產業別" in tr:
            # 產業別分隔列（可能是 th），從整列文字抓「產業別：XXX」到「單位」之間
            m = re.search(r"產業別[：:]\s*(.+?)\s*單位", _TAG_RE.sub("", tr))
            if m:
                industry = m.group(1).strip() or None
            continue
        cells = [_cell_text(c) for c in _TD_RE.findall(tr)]
        if not cells or not re.fullmatch(r"\d{4,}", cells[0]) or len(cells) < 10:
            continue  # 跳過合計列、表頭、空列
        rev = _num(cells[2].replace(",", ""), True)
        rev_ly = _num(cells[4].replace(",", ""), True)
        yoy = (round((rev - rev_ly) / rev_ly * 100, 2)
               if rev is not None and rev_ly not in (None, 0) else None)
        out.append({
            "ticker": cells[0], "ym": ym, "name": cells[1], "industry": industry,
            "market": market,
            "rev": rev,
            "rev_prev": _num(cells[3].replace(",", ""), True),
            "rev_ly": rev_ly,
            "mom_pct": _num(cells[5], False),
            "yoy_pct": yoy,
            "cum": _num(cells[6].replace(",", ""), True),
            "cum_ly": _num(cells[7].replace(",", ""), True),
            "cum_yoy_pct": _num(cells[8], False),
            "memo": cells[9] if cells[9] not in ("-", "") else None,
        })
    return out


def fetch_monthly_revenue_mops(year: int, month: int) -> dict:
    """回補單一月份（西元 year/month）的上市+上櫃月營收，資料來源 MOPS t21sc03。"""
    roc = year - 1911
    ym = f"{year}-{month:02d}"
    records: list[dict] = []
    by_market = {}
    for market, seg in _MOPS_SEG.items():
        url = MOPS_URL.format(seg=seg, roc=roc, month=month)
        resp = _tpex_get(url, headers=_TWSE_HEADERS, timeout=30)  # 放寬 SSL
        resp.raise_for_status()
        html = resp.content.decode("big5", errors="replace")
        rows = _parse_mops(html, ym, market)
        records += rows
        by_market[market] = len(rows)
    saved = bulk_save_monthly_revenue(records) if records else 0
    _board_cache.clear()
    return {"ym": ym, "saved": saved, "by_market": by_market}


def _flag_12m_high(rows: list[dict], ym: str) -> None:
    """就地在每列加 is_12m_high：當月營收是近 12 個月（含當月）最大才為 True。
    歷史不足 12 個月時標 None（前端顯示「資料累積中」）。"""
    for r in rows:
        hist = get_ticker_revenue_history(r["ticker"], 12)
        revs = [h["rev"] for h in hist if h["rev"] is not None]
        if len(revs) < 12 or r.get("rev") is None:
            r["is_12m_high"] = None
        else:
            r["is_12m_high"] = r["rev"] >= max(revs)


def get_revenue_board(ym: str | None = None) -> dict:
    """回傳某月全部股票營收 + meta。榜單排序與篩選交給前端。"""
    months = get_revenue_months()
    if not months:
        return {"ym": None, "months": [], "rows": []}
    if ym not in months:
        ym = months[0]

    cached = _board_cache.get(ym)
    if cached and time.time() - cached[0] < BOARD_TTL:
        return cached[1]

    rows = get_revenue_by_month(ym)
    _flag_12m_high(rows, ym)
    result = {"ym": ym, "months": months, "rows": rows}
    _board_cache[ym] = (time.time(), result)
    return result


def get_revenue_industry(ym: str | None = None, market: str | None = None) -> dict:
    """產業成長榜：同產業當月營收合計、去年同月合計，算年增率。"""
    board = get_revenue_board(ym)
    agg: dict = {}
    for r in board["rows"]:
        if market and r["market"] != market:
            continue
        ind = r.get("industry") or "其他"
        a = agg.setdefault(ind, {"industry": ind, "rev": 0, "rev_ly": 0, "count": 0})
        if r.get("rev"):
            a["rev"] += r["rev"]
        if r.get("rev_ly"):
            a["rev_ly"] += r["rev_ly"]
        a["count"] += 1

    out = []
    for a in agg.values():
        a["yoy_pct"] = (round((a["rev"] - a["rev_ly"]) / a["rev_ly"] * 100, 2)
                        if a["rev_ly"] else None)
        out.append(a)
    out.sort(key=lambda x: (x["yoy_pct"] is not None, x["yoy_pct"] or 0), reverse=True)
    return {"ym": board["ym"], "industries": out}
