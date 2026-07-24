"""權證：查某支股票目前有哪些權證，附即時履約價/到期日/價內外程度/簡單槓桿倍數。

架構說明：權證→標的股的對照表是每日排程批次更新（TWSE/TPEx 官方發行清單，不含即時
報價），但每檔權證的即時價格/履約價/到期日是使用者打開個股頁「權證」分頁時才即時
查 Fugle（用執行緒池平行查，不是排程批次），這樣才不會讓每天已經要跑很久的
daily_update.py 又變得更慢。
"""
import time
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services.stock_data import _get_fugle, _fugle_quote, _tpex_get, _parse_num, get_stock_info

_TWSE_WARRANT_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap36_L"
_TPEX_WARRANT_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap36_O"


def _roc_to_ad(s: str) -> str:
    """民國年字串（如 "1140731"）轉西元 "YYYY-MM-DD"，格式不對就回傳空字串。"""
    s = (s or "").strip()
    if len(s) != 7 or not s.isdigit():
        return ""
    year = int(s[:3]) + 1911
    return f"{year}-{s[3:5]}-{s[5:7]}"


def fetch_warrants_today() -> list[dict]:
    """抓 TWSE+TPEx 權證發行清單，依權證代號去重（同代號因增額發行會有多筆，取發行日期最新一筆）。"""
    import requests
    latest: dict[str, dict] = {}

    def _ingest(rows, code_key, name_key, under_code_key, under_name_key, issuer_key, date_key):
        for row in rows:
            code = str(row.get(code_key, "")).strip()
            under_code = str(row.get(under_code_key, "")).strip()
            if not code or not under_code:
                continue
            issue_date = _roc_to_ad(row.get(date_key, ""))
            existing = latest.get(code)
            if existing and existing["issue_date"] >= issue_date:
                continue
            latest[code] = {
                "ticker": code,
                "name": str(row.get(name_key, "")).strip(),
                "underlying_ticker": under_code,
                "underlying_name": str(row.get(under_name_key, "")).strip(),
                "issuer_name": str(row.get(issuer_key, "")).strip(),
                "issue_date": issue_date,
            }

    try:
        resp = requests.get(_TWSE_WARRANT_URL, timeout=30)
        _ingest(resp.json(), "權證代號", "名稱", "標的代號", "標的名稱", "發行人名稱", "申請發行日期")
    except Exception as e:
        print(f"[權證] TWSE 抓取失敗: {e}")

    try:
        resp = _tpex_get(_TPEX_WARRANT_URL)
        _ingest(resp.json(), "權證代號", "名稱", "標的代號", "標的名稱", "發行人名稱", "申請發行日期")
    except Exception as e:
        print(f"[權證] TPEx 抓取失敗: {e}")

    return list(latest.values())


def _fugle_warrant_detail(ticker: str) -> dict | None:
    """單一權證的即時資料：履約價/行使比例/到期日 + 現價/漲跌（合併 intraday/ticker + _fugle_quote）。"""
    client = _get_fugle()
    if not client:
        return None
    try:
        resp = client.stock.intraday.ticker(symbol=ticker)
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        if not isinstance(data, dict) or not data.get("exercisePrice"):
            return None
        quote = _fugle_quote(ticker)
        return {
            "ticker": ticker,
            "name": data.get("name") or quote.get("name"),
            "price": quote.get("price"),
            "change": quote.get("change"),
            "change_pct": quote.get("change_pct"),
            "exercise_price": data.get("exercisePrice"),
            "exercise_ratio": data.get("exerciseRatio"),
            "maturity_date": data.get("maturityDate"),  # 格式 YYYYMMDD
        }
    except Exception:
        return None


def get_stock_warrants(underlying_ticker: str, limit: int = 40) -> list[dict]:
    """某標的股目前可交易的權證清單，附價內外程度/簡單槓桿倍數，依剩餘天數排序。"""
    from app.db import get_warrants_by_underlying

    candidates = get_warrants_by_underlying(underlying_ticker, limit=80)
    if not candidates:
        return []

    meta_by_ticker = {c["ticker"]: c for c in candidates}
    details: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fugle_warrant_detail, c["ticker"]): c["ticker"] for c in candidates}
        for fut in as_completed(futures):
            t = futures[fut]
            d = fut.result()
            if d:
                details[t] = d

    underlying_price = (get_stock_info(underlying_ticker) or {}).get("price")
    today = date.today()
    results = []
    for ticker, d in details.items():
        maturity_raw = d.get("maturity_date")
        if not maturity_raw or len(str(maturity_raw)) != 8:
            continue
        try:
            maturity = datetime.strptime(str(maturity_raw), "%Y%m%d").date()
        except ValueError:
            continue
        days_left = (maturity - today).days
        if days_left < 0:
            continue  # 已到期

        meta = meta_by_ticker.get(ticker, {})
        name = d.get("name") or meta.get("name") or ""
        exercise_price = d.get("exercise_price")
        exercise_ratio = d.get("exercise_ratio")
        price = d.get("price")
        is_put = "售" in name  # 台灣權證命名慣例：名稱一定含「購」或「售」

        moneyness_pct = None
        if underlying_price and exercise_price:
            if is_put:
                moneyness_pct = round((exercise_price - underlying_price) / exercise_price * 100, 2)
            else:
                moneyness_pct = round((underlying_price - exercise_price) / exercise_price * 100, 2)

        leverage = None
        if underlying_price and exercise_ratio and price:
            leverage = round(underlying_price * exercise_ratio / price, 2)

        results.append({
            "ticker": ticker,
            "name": name,
            "issuer_name": meta.get("issuer_name"),
            "price": price,
            "change": d.get("change"),
            "change_pct": d.get("change_pct"),
            "exercise_price": exercise_price,
            "maturity_date": maturity.strftime("%Y-%m-%d"),
            "days_left": days_left,
            "is_put": is_put,
            "moneyness_pct": moneyness_pct,
            "leverage": leverage,
        })

    results.sort(key=lambda r: r["days_left"])
    return results[:limit]
