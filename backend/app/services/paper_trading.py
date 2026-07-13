from app.db import (
    get_or_create_paper_account, update_paper_cash,
    get_paper_position, upsert_paper_position, get_paper_positions,
    insert_paper_order, get_paper_orders, get_paper_realized_pl_total,
    reset_paper_account,
)
from app.services.stock_data import get_stock_info

COMMISSION_RATE = 0.001425
COMMISSION_MIN  = 20
TAX_RATE        = 0.003  # 現股賣出證交稅


class PaperTradingError(Exception):
    pass


def _fee(amount: float) -> float:
    return max(round(amount * COMMISSION_RATE), COMMISSION_MIN)


def _tax(amount: float) -> float:
    return round(amount * TAX_RATE)


def place_market_order(user_id: int, ticker: str, side: str, lots: int) -> dict:
    qty = lots * 1000
    info  = get_stock_info(ticker)
    price = info.get("price")
    name  = info.get("name")
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
            "market_value":  round(market_value, 2) if market_value is not None else None,
            "unrealized_pl": round(unrealized_pl, 2) if unrealized_pl is not None else None,
            "return_pct":    round(unrealized_pl / cost_basis * 100, 2) if unrealized_pl is not None and cost_basis else None,
        })
    return result


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


def reset_account(user_id: int) -> dict:
    reset_paper_account(user_id)
    return get_account_summary(user_id)
