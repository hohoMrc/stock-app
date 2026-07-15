from datetime import date, datetime

from app.db import (
    get_or_create_paper_account, update_paper_cash,
    get_paper_position, upsert_paper_position, get_paper_positions,
    insert_paper_order, get_paper_orders, get_paper_realized_pl_total,
    get_paper_bought_qty_since,
)
from app.services.stock_data import get_stock_info, _enrich_with_intraday

COMMISSION_RATE = 0.001425
COMMISSION_MIN  = 20
TAX_RATE        = 0.003  # 現股賣出證交稅
DEPOSIT_AMOUNT  = 100_000  # 入金金額


class PaperTradingError(Exception):
    pass


def _fee(amount: float) -> float:
    return max(round(amount * COMMISSION_RATE), COMMISSION_MIN)


def _tax(amount: float) -> float:
    return round(amount * TAX_RATE)


def _today_start_ts() -> float:
    return datetime.combine(date.today(), datetime.min.time()).timestamp()


def place_market_order(user_id: int, ticker: str, side: str, lots: int, price: float | None = None) -> dict:
    """price 未提供時用即時市價成交；有提供時直接以該價格成交（不掛單等待，送出當下立即記帳）。"""
    qty = lots * 1000
    info  = get_stock_info(ticker)
    name  = info.get("name")
    if price is not None:
        if price <= 0:
            raise PaperTradingError("價格需大於 0")
    else:
        price = info.get("price")
    if not price:
        raise PaperTradingError("目前無法取得該股票報價，請稍後再試")

    account  = get_or_create_paper_account(user_id)
    position = get_paper_position(user_id, ticker)
    gross    = price * qty

    if side == "buy":
        fee  = _fee(gross)
        cost = gross + fee
        if cost > account["cash"]:
            raise PaperTradingError("現金不足")

        old_qty, old_avg = (position["qty"], position["avg_cost"]) if position else (0, 0.0)
        new_qty = old_qty + qty
        new_avg = (old_qty * old_avg + cost) / new_qty

        update_paper_cash(user_id, account["cash"] - cost)
        upsert_paper_position(user_id, ticker, new_qty, new_avg)
        insert_paper_order(user_id, ticker, name, "buy", qty, price, fee, 0, cost, None)
        return {"ticker": ticker, "name": name, "side": "buy", "qty": qty,
                "price": price, "fee": fee, "tax": 0, "net_amount": cost, "realized_pl": None}

    if side == "sell":
        held = position["qty"] if position else 0
        if qty > held:
            raise PaperTradingError("持股不足")

        bought_today = get_paper_bought_qty_since(user_id, ticker, _today_start_ts())
        sellable = max(0, held - bought_today)
        if qty > sellable:
            raise PaperTradingError("現股不可當沖：今日買進的部位不可當日賣出")

        fee = _fee(gross)
        tax = _tax(gross)
        net = gross - fee - tax
        realized_pl = net - position["avg_cost"] * qty

        update_paper_cash(user_id, account["cash"] + net)
        upsert_paper_position(user_id, ticker, held - qty, position["avg_cost"])
        insert_paper_order(user_id, ticker, name, "sell", qty, price, fee, tax, net, realized_pl)
        return {"ticker": ticker, "name": name, "side": "sell", "qty": qty,
                "price": price, "fee": fee, "tax": tax, "net_amount": net, "realized_pl": realized_pl}

    raise PaperTradingError("side 需為 buy 或 sell")


def _info_for(ticker: str) -> dict:
    try:
        return get_stock_info(ticker)
    except Exception:
        return {}


def get_positions_with_price(user_id: int) -> list[dict]:
    positions = get_paper_positions(user_id)
    result = []
    for p in positions:
        info  = _info_for(p["ticker"])
        price = info.get("price")
        market_value  = price * p["qty"] if price else None
        cost_basis    = p["avg_cost"] * p["qty"]
        unrealized_pl = (market_value - cost_basis) if market_value is not None else None
        result.append({
            "ticker":        p["ticker"],
            "name":          info.get("name"),
            "lots":          p["qty"] // 1000,
            "qty":           p["qty"],
            "avg_cost":      round(p["avg_cost"], 2),
            "price":         price,
            "change":        info.get("change"),
            "change_pct":    info.get("change_pct"),
            "volume_zhang":  info.get("volume_zhang"),
            "market_value":  round(market_value, 2) if market_value is not None else None,
            "unrealized_pl": round(unrealized_pl, 2) if unrealized_pl is not None else None,
            "return_pct":    round(unrealized_pl / cost_basis * 100, 2) if unrealized_pl is not None and cost_basis else None,
        })
    # 補上委買/委賣/單量等五檔資訊（漲跌停鎖死時 WebSocket 可能完全不推播，靠這裡的初始 REST 值墊底）
    return _enrich_with_intraday(result)


def get_account_summary(user_id: int) -> dict:
    account   = get_or_create_paper_account(user_id)
    positions = get_positions_with_price(user_id)
    market_value_total = sum(p["market_value"] for p in positions if p["market_value"] is not None)
    unrealized_total    = sum(p["unrealized_pl"] for p in positions if p["unrealized_pl"] is not None)
    realized_total       = get_paper_realized_pl_total(user_id)
    equity = account["cash"] + market_value_total
    return {
        "cash":               round(account["cash"], 2),
        "market_value":       round(market_value_total, 2),
        "equity":             round(equity, 2),
        "unrealized_pl":      round(unrealized_total, 2),
        "realized_pl":        round(realized_total, 2),
    }


def get_order_history(user_id: int, limit: int = 50) -> list[dict]:
    return get_paper_orders(user_id, limit)


def deposit_cash(user_id: int) -> dict:
    """入金：現金加上固定金額，並在歷史紀錄留一筆入金記錄，不動持股。"""
    account = get_or_create_paper_account(user_id)
    update_paper_cash(user_id, account["cash"] + DEPOSIT_AMOUNT)
    insert_paper_order(user_id, "CASH", "入金", "deposit", 0, 0, 0, 0, DEPOSIT_AMOUNT, None)
    return get_account_summary(user_id)
