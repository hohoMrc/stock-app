from datetime import datetime

from app.db import (
    get_or_create_paper_futures_account, update_paper_futures_cash,
    get_paper_futures_position, upsert_paper_futures_position, get_paper_futures_positions,
    insert_paper_futures_order, get_paper_futures_orders, get_paper_futures_closed_trades,
    create_conditional_order, get_conditional_orders, get_pending_conditional_orders,
    mark_conditional_order_triggered, mark_conditional_order_failed, cancel_conditional_order,
)
from app.services.futures_data import _current_symbol, get_futures_quote

# 每點台幣（TXF：大台指=台股期貨 NT$200/點；TMF：微台指=微型臺指期貨 NT$10/點，
# 不是小型臺指期貨 NT$50/點——app 內部代號 TMF 只是自己取的，非期交所官方 MTX 代碼）
FUTURES_MULTIPLIER = {"TXF": 200, "TMF": 10}
# 原始保證金約略值（僅供模擬參考，實際保證金依期交所公告會隨波動度調整，不是即時抓的）
FUTURES_MARGIN = {"TXF": 184_000, "TMF": 9_200}

FEE_PER_LOT = 50        # 每口每邊手續費約略值
TAX_RATE = 0.00002      # 期交稅
DEPOSIT_AMOUNT = 500_000


class PaperFuturesError(Exception):
    pass


def _fee(qty: int) -> float:
    return FEE_PER_LOT * qty


def _tax(price: float, qty: int, product: str) -> float:
    return round(price * FUTURES_MULTIPLIER[product] * qty * TAX_RATE)


def _current_price(product: str) -> float | None:
    try:
        symbol = _current_symbol(product)
        return get_futures_quote(symbol).get("price")
    except Exception:
        return None


def _used_margin(user_id: int) -> float:
    positions = get_paper_futures_positions(user_id)
    return sum(p["qty"] * FUTURES_MARGIN[p["product"]] for p in positions)


def place_futures_order(user_id: int, product: str, side: str, action: str, qty: int,
                         price: float | None = None) -> dict:
    """price 未提供時用即時市價成交；有提供時直接以該價格成交（不掛單等待，送出當下立即記帳）。
    同一商品同時只能持有單一方向部位：action="open" 時若已有反方向部位會被拒絕，要先平倉。
    """
    if product not in FUTURES_MULTIPLIER:
        raise PaperFuturesError("product 需為 TXF 或 TMF")
    if side not in ("long", "short"):
        raise PaperFuturesError("side 需為 long 或 short")
    if action not in ("open", "close"):
        raise PaperFuturesError("action 需為 open 或 close")
    if qty <= 0:
        raise PaperFuturesError("口數需大於 0")

    if price is not None:
        if price <= 0:
            raise PaperFuturesError("價格需大於 0")
    else:
        price = _current_price(product)
    if not price:
        raise PaperFuturesError("目前無法取得期貨報價，請稍後再試")

    account  = get_or_create_paper_futures_account(user_id)
    position = get_paper_futures_position(user_id, product)
    multiplier = FUTURES_MULTIPLIER[product]
    fee = _fee(qty)

    if action == "open":
        if position and position["side"] != side:
            raise PaperFuturesError("目前持有反向部位，請先平倉")

        required_margin = qty * FUTURES_MARGIN[product]
        available = account["cash"] - _used_margin(user_id)
        if required_margin + fee > available:
            raise PaperFuturesError("可用保證金不足")

        old_qty, old_avg = (position["qty"], position["avg_price"]) if position else (0, 0.0)
        new_qty = old_qty + qty
        new_avg = (old_qty * old_avg + qty * price) / new_qty

        update_paper_futures_cash(user_id, account["cash"] - fee)
        upsert_paper_futures_position(user_id, product, side, new_qty, new_avg)
        insert_paper_futures_order(user_id, product, side, "open", qty, price, fee, 0, fee, None)
        return {"product": product, "side": side, "action": "open", "qty": qty,
                "price": price, "fee": fee, "tax": 0, "net_amount": fee, "realized_pl": None}

    # action == "close"
    if not position or position["side"] != side:
        raise PaperFuturesError(f"目前沒有{'多' if side == 'long' else '空'}單部位可平")
    if qty > position["qty"]:
        raise PaperFuturesError("平倉口數超過持有口數")

    tax = _tax(price, qty, product)
    if side == "long":
        realized_pl = (price - position["avg_price"]) * qty * multiplier
    else:
        realized_pl = (position["avg_price"] - price) * qty * multiplier
    net_amount = realized_pl - fee - tax

    update_paper_futures_cash(user_id, account["cash"] + net_amount)
    upsert_paper_futures_position(user_id, product, side, position["qty"] - qty, position["avg_price"])
    insert_paper_futures_order(user_id, product, side, "close", qty, price, fee, tax, net_amount, realized_pl)
    return {"product": product, "side": side, "action": "close", "qty": qty,
            "price": price, "fee": fee, "tax": tax, "net_amount": net_amount, "realized_pl": realized_pl}


def get_futures_positions_with_price(user_id: int) -> list[dict]:
    positions = get_paper_futures_positions(user_id)
    result = []
    for p in positions:
        product = p["product"]
        multiplier = FUTURES_MULTIPLIER[product]
        price = _current_price(product)
        if price is not None:
            if p["side"] == "long":
                unrealized_pl = (price - p["avg_price"]) * p["qty"] * multiplier
            else:
                unrealized_pl = (p["avg_price"] - price) * p["qty"] * multiplier
        else:
            unrealized_pl = None
        result.append({
            "product":       product,
            "side":          p["side"],
            "qty":           p["qty"],
            "avg_price":     round(p["avg_price"], 2),
            "price":         price,
            "margin":        p["qty"] * FUTURES_MARGIN[product],
            "unrealized_pl": round(unrealized_pl, 2) if unrealized_pl is not None else None,
        })
    return result


def get_futures_account_summary(user_id: int) -> dict:
    account   = get_or_create_paper_futures_account(user_id)
    positions = get_futures_positions_with_price(user_id)
    used_margin      = sum(p["margin"] for p in positions)
    unrealized_total = sum(p["unrealized_pl"] for p in positions if p["unrealized_pl"] is not None)
    equity = account["cash"] + unrealized_total
    return {
        "cash":             round(account["cash"], 2),
        "used_margin":      round(used_margin, 2),
        "available_margin": round(account["cash"] - used_margin, 2),
        "unrealized_pl":    round(unrealized_total, 2),
        "equity":           round(equity, 2),
    }


def get_futures_performance_stats(user_id: int) -> dict:
    """已平倉交易統計：勝率、平均獲利/虧損、損益比、累計已實現損益走勢。"""
    trades = get_paper_futures_closed_trades(user_id)
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
        "total_trades":      total,
        "win_count":         len(wins),
        "loss_count":        len(losses),
        "win_rate":          win_rate,
        "avg_win":           avg_win,
        "avg_loss":          avg_loss,
        "profit_factor":     profit_factor,
        "total_realized_pl": total_realized_pl,
        "curve":             curve,
    }


def get_futures_order_history(user_id: int, limit: int = 50) -> list[dict]:
    return get_paper_futures_orders(user_id, limit)


def deposit_futures_cash(user_id: int) -> dict:
    """入金：現金加上固定金額，並在歷史紀錄留一筆入金記錄，不動部位。"""
    account = get_or_create_paper_futures_account(user_id)
    update_paper_futures_cash(user_id, account["cash"] + DEPOSIT_AMOUNT)
    insert_paper_futures_order(user_id, "CASH", "long", "deposit", 0, 0, 0, 0, DEPOSIT_AMOUNT, None)
    return get_futures_account_summary(user_id)


# ── 智慧單（到價自動下單）─────────────────────────────────

def create_smart_order(user_id: int, product: str, side: str, action: str, qty: int,
                        trigger_price: float) -> dict:
    """設定「指數到多少自動下單」。direction 不用使用者選，用目前市價跟 trigger_price
    的相對關係自動判斷：trigger_price >= 目前市價 → 等漲到這個價位（above），
    否則等跌到這個價位（below）——跟真實下單軟體設定停利/停損價的直覺一致。
    """
    if product not in FUTURES_MULTIPLIER:
        raise PaperFuturesError("product 需為 TXF 或 TMF")
    if side not in ("long", "short"):
        raise PaperFuturesError("side 需為 long 或 short")
    if action not in ("open", "close"):
        raise PaperFuturesError("action 需為 open 或 close")
    if qty <= 0:
        raise PaperFuturesError("口數需大於 0")
    if trigger_price <= 0:
        raise PaperFuturesError("觸發價格需大於 0")

    current = _current_price(product)
    if not current:
        raise PaperFuturesError("目前無法取得期貨報價，請稍後再試")

    direction = "above" if trigger_price >= current else "below"
    order_id = create_conditional_order(user_id, product, side, action, qty, trigger_price, direction)
    return {
        "id": order_id, "product": product, "side": side, "action": action, "qty": qty,
        "trigger_price": trigger_price, "direction": direction, "status": "pending",
    }


def get_smart_orders(user_id: int) -> list[dict]:
    return get_conditional_orders(user_id)


def cancel_smart_order(user_id: int, order_id: int) -> bool:
    return cancel_conditional_order(user_id, order_id)


def check_and_execute_conditional_orders() -> list[dict]:
    """輪詢進入點，供 futures_conditional_check.py 排程呼叫。對每筆待觸發智慧單比對目前市價，
    觸發就用當下市價（不是 trigger_price 本身，跟真實停損/停利單一樣「觸價後市價成交」）
    呼叫 place_futures_order() 真的幫使用者下單。回傳這一輪有處理到的結果，供排程腳本發 TG 通知。
    """
    pending = get_pending_conditional_orders()
    if not pending:
        return []

    price_cache: dict[str, float | None] = {}
    results = []
    for o in pending:
        product = o["product"]
        if product not in price_cache:
            price_cache[product] = _current_price(product)
        price = price_cache[product]
        if price is None:
            continue

        hit = (o["direction"] == "above" and price >= o["trigger_price"]) or \
              (o["direction"] == "below" and price <= o["trigger_price"])
        if not hit:
            continue

        try:
            order = place_futures_order(o["user_id"], product, o["side"], o["action"], o["qty"])
            mark_conditional_order_triggered(o["id"])
            results.append({**o, "result": "triggered", "fill_price": order["price"],
                             "realized_pl": order.get("realized_pl")})
        except PaperFuturesError as e:
            mark_conditional_order_failed(o["id"], str(e))
            results.append({**o, "result": "failed", "fail_reason": str(e)})

    return results
