from datetime import datetime

from app.db import (
    get_or_create_paper_daytrade_account, update_paper_daytrade_cash,
    get_paper_daytrade_position, upsert_paper_daytrade_position, get_paper_daytrade_positions,
    insert_paper_daytrade_order, get_paper_daytrade_orders, get_paper_daytrade_realized_pl_total,
    get_paper_daytrade_closed_trades,
)
from app.services.paper_trading import COMMISSION_RATE, COMMISSION_MIN, DAY_TRADE_TAX_RATE
from app.services.stock_data import get_stock_info, _enrich_with_intraday

DEPOSIT_AMOUNT = 100_000  # 入金金額


class PaperDaytradeError(Exception):
    pass


def _fee(amount: float) -> float:
    return max(round(amount * COMMISSION_RATE), COMMISSION_MIN)


def _tax(amount: float) -> float:
    return round(amount * DAY_TRADE_TAX_RATE)


def place_daytrade_order(user_id: int, ticker: str, side: str, lots: int,
                          price: float | None = None) -> dict:
    """當沖練習專用下單，跟一般模擬下單（app/services/paper_trading.py）是分開的帳戶。
    刻意不檢查「現金是否足夠」——真實現股當沖本來就不需要準備全額本金，只要求收盤前
    一定要把部位沖銷掉，本金限制反而會擋住當沖練習。也不檢查「今日買進不可當日賣出」，
    這個帳戶每一筆賣出都當作當沖處理，證交稅固定用當沖減半稅率。跟一般模擬下單一樣
    不支援先賣後補，賣出不能超過目前持股。
    """
    qty = lots * 1000
    info  = get_stock_info(ticker)
    name  = info.get("name")
    if price is not None:
        if price <= 0:
            raise PaperDaytradeError("價格需大於 0")
    else:
        price = info.get("price")
    if not price:
        raise PaperDaytradeError("目前無法取得該股票報價，請稍後再試")

    account  = get_or_create_paper_daytrade_account(user_id)
    position = get_paper_daytrade_position(user_id, ticker)
    gross    = price * qty

    if side == "buy":
        fee  = _fee(gross)
        cost = gross + fee

        old_qty, old_avg = (position["qty"], position["avg_cost"]) if position else (0, 0.0)
        new_qty = old_qty + qty
        new_avg = (old_qty * old_avg + cost) / new_qty

        update_paper_daytrade_cash(user_id, account["cash"] - cost)
        upsert_paper_daytrade_position(user_id, ticker, new_qty, new_avg)
        insert_paper_daytrade_order(user_id, ticker, name, "buy", qty, price, fee, 0, cost, None)
        return {"ticker": ticker, "name": name, "side": "buy", "qty": qty,
                "price": price, "fee": fee, "tax": 0, "net_amount": cost, "realized_pl": None}

    if side == "sell":
        held = position["qty"] if position else 0
        if qty > held:
            raise PaperDaytradeError("持股不足（這裡不支援先賣後補，賣出不能超過目前持股）")

        fee = _fee(gross)
        tax = _tax(gross)
        net = gross - fee - tax
        realized_pl = net - position["avg_cost"] * qty

        update_paper_daytrade_cash(user_id, account["cash"] + net)
        upsert_paper_daytrade_position(user_id, ticker, held - qty, position["avg_cost"])
        insert_paper_daytrade_order(user_id, ticker, name, "sell", qty, price, fee, tax, net, realized_pl)
        return {"ticker": ticker, "name": name, "side": "sell", "qty": qty,
                "price": price, "fee": fee, "tax": tax, "net_amount": net, "realized_pl": realized_pl}

    raise PaperDaytradeError("side 需為 buy 或 sell")


def _info_for(ticker: str) -> dict:
    try:
        return get_stock_info(ticker)
    except Exception:
        return {}


def get_positions_with_price(user_id: int) -> list[dict]:
    positions = get_paper_daytrade_positions(user_id)
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
    return _enrich_with_intraday(result)


def get_account_summary(user_id: int) -> dict:
    account   = get_or_create_paper_daytrade_account(user_id)
    positions = get_positions_with_price(user_id)
    market_value_total = sum(p["market_value"] for p in positions if p["market_value"] is not None)
    unrealized_total    = sum(p["unrealized_pl"] for p in positions if p["unrealized_pl"] is not None)
    realized_total       = get_paper_daytrade_realized_pl_total(user_id)
    equity = account["cash"] + market_value_total
    return {
        "cash":               round(account["cash"], 2),
        "market_value":       round(market_value_total, 2),
        "equity":             round(equity, 2),
        "unrealized_pl":      round(unrealized_total, 2),
        "realized_pl":        round(realized_total, 2),
    }


def get_performance_stats(user_id: int) -> dict:
    """已平倉交易統計：勝率、平均獲利/虧損、損益比、累計已實現損益走勢。"""
    trades = get_paper_daytrade_closed_trades(user_id)
    total = len(trades)
    wins   = [t for t in trades if t["realized_pl"] > 0]
    losses = [t for t in trades if t["realized_pl"] < 0]

    win_rate = round(len(wins) / total * 100, 1) if total else None
    avg_win  = round(sum(t["realized_pl"] for t in wins) / len(wins), 2) if wins else None
    avg_loss = round(sum(t["realized_pl"] for t in losses) / len(losses), 2) if losses else None
    gross_win  = sum(t["realized_pl"] for t in wins)
    gross_loss = abs(sum(t["realized_pl"] for t in losses))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss else None
    total_realized_pl = round(sum(t["realized_pl"] for t in trades), 2)

    cumulative = 0
    curve = []
    for t in trades:
        cumulative += t["realized_pl"]
        curve.append({
            "date": datetime.fromtimestamp(t["created_at"]).strftime("%Y-%m-%d"),
            "cumulative_pl": round(cumulative, 2),
        })

    return {
        "total_trades":     total,
        "win_count":        len(wins),
        "loss_count":       len(losses),
        "win_rate":         win_rate,
        "avg_win":          avg_win,
        "avg_loss":         avg_loss,
        "profit_factor":    profit_factor,
        "total_realized_pl": total_realized_pl,
        "curve":            curve,
    }


def get_order_history(user_id: int, limit: int = 50) -> list[dict]:
    return get_paper_daytrade_orders(user_id, limit)


def deposit_cash(user_id: int) -> dict:
    """入金：現金加上固定金額，並在歷史紀錄留一筆入金記錄，不動持股。"""
    account = get_or_create_paper_daytrade_account(user_id)
    update_paper_daytrade_cash(user_id, account["cash"] + DEPOSIT_AMOUNT)
    insert_paper_daytrade_order(user_id, "CASH", "入金", "deposit", 0, 0, 0, 0, DEPOSIT_AMOUNT, None)
    return {**get_account_summary(user_id), "deposit_amount": DEPOSIT_AMOUNT}
