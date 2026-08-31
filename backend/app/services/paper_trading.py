from datetime import date, datetime

from app.db import (
    get_or_create_paper_account, update_paper_cash,
    get_paper_position, upsert_paper_position, get_paper_positions,
    insert_paper_order, get_paper_orders, get_paper_realized_pl_total,
    get_paper_bought_qty_since, get_paper_closed_trades,
    create_stock_conditional_order, get_stock_conditional_orders, get_pending_stock_conditional_orders,
    mark_stock_conditional_order_triggered, mark_stock_conditional_order_failed, cancel_stock_conditional_order,
    update_stock_conditional_order_note,
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


def place_market_order(user_id: int, ticker: str, side: str, lots: int, price: float | None = None,
                        reason: str | None = None, allow_day_trade: bool = False) -> dict:
    """price 未提供時用即時市價成交；有提供時直接以該價格成交（不掛單等待，送出當下立即記帳）。
    reason：記錄這筆單是為什麼下的（目前給 Claude 自動交易用，一般使用者手動下單不會傳）。
    allow_day_trade：跳過「今日買進不可當日賣出」的現股限制，只給當沖模擬帳戶用——
    一般使用者手動下單、長期/短期 Claude 帳戶都要保留這個限制，模擬真實現股規則。
    """
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
        insert_paper_order(user_id, ticker, name, "buy", qty, price, fee, 0, cost, None, reason)
        return {"ticker": ticker, "name": name, "side": "buy", "qty": qty,
                "price": price, "fee": fee, "tax": 0, "net_amount": cost, "realized_pl": None}

    if side == "sell":
        held = position["qty"] if position else 0
        if qty > held:
            raise PaperTradingError("持股不足")

        if not allow_day_trade:
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
        insert_paper_order(user_id, ticker, name, "sell", qty, price, fee, tax, net, realized_pl, reason)
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


def get_performance_stats(user_id: int) -> dict:
    """已平倉交易統計：勝率、平均獲利/虧損、損益比、累計已實現損益走勢。"""
    trades = get_paper_closed_trades(user_id)
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
    return get_paper_orders(user_id, limit)


def deposit_cash(user_id: int) -> dict:
    """入金：現金加上固定金額，並在歷史紀錄留一筆入金記錄，不動持股。"""
    account = get_or_create_paper_account(user_id)
    update_paper_cash(user_id, account["cash"] + DEPOSIT_AMOUNT)
    insert_paper_order(user_id, "CASH", "入金", "deposit", 0, 0, 0, 0, DEPOSIT_AMOUNT, None)
    return {**get_account_summary(user_id), "deposit_amount": DEPOSIT_AMOUNT}


# ── 智慧單（到價自動買賣）─────────────────────────────────

def create_smart_order(user_id: int, ticker: str, side: str, lots: int, trigger_price: float,
                        order_type: str = "stop") -> dict:
    """設定「股價到多少自動下單」。direction 不用使用者選，用目前市價跟 trigger_price
    的相對關係自動判斷：trigger_price >= 目前市價 → 等漲到這個價位（above），
    否則等跌到這個價位（below）。
    order_type: "stop"（觸價後用當下市價成交，可能有滑價）或 "limit"（觸價後直接用
    trigger_price 成交，價格不會跑掉）。
    """
    if side not in ("buy", "sell"):
        raise PaperTradingError("side 需為 buy 或 sell")
    if lots <= 0:
        raise PaperTradingError("張數需大於 0")
    if trigger_price <= 0:
        raise PaperTradingError("觸發價格需大於 0")
    if order_type not in ("stop", "limit"):
        raise PaperTradingError("order_type 需為 stop 或 limit")

    current = get_stock_info(ticker).get("price")
    if not current:
        raise PaperTradingError("目前無法取得該股票報價，請稍後再試")

    direction = "above" if trigger_price >= current else "below"
    order_id = create_stock_conditional_order(user_id, ticker, side, lots, trigger_price, direction, order_type)
    return {
        "id": order_id, "ticker": ticker, "side": side, "lots": lots,
        "trigger_price": trigger_price, "direction": direction, "order_type": order_type, "status": "pending",
    }


def get_smart_orders(user_id: int) -> list[dict]:
    return get_stock_conditional_orders(user_id)


def cancel_smart_order(user_id: int, order_id: int) -> bool:
    return cancel_stock_conditional_order(user_id, order_id)


def update_smart_order_note(user_id: int, order_id: int, note: str) -> bool:
    return update_stock_conditional_order_note(user_id, order_id, note)


def check_and_execute_conditional_orders() -> list[dict]:
    """輪詢進入點，供 stock_conditional_check.py 排程呼叫。對每筆待觸發智慧單比對目前股價，
    觸發就呼叫 place_market_order() 真的幫使用者下單：order_type="stop" 用當下市價成交
    （可能有滑價），"limit" 直接用 trigger_price 成交。
    現金不足/持股不足/現股不可當沖等既有限制在觸發當下才驗證，失敗會標記原因（尤其是當沖
    限制：智慧單常見情境是「買進後同一天股價漲到X就賣出」，剛好會踩到這個限制）。
    回傳這一輪有處理到的結果，供排程腳本發 TG 通知。
    """
    pending = get_pending_stock_conditional_orders()
    if not pending:
        return []

    price_cache: dict[str, float | None] = {}
    results = []
    for o in pending:
        ticker = o["ticker"]
        if ticker not in price_cache:
            price_cache[ticker] = _info_for(ticker).get("price")
        price = price_cache[ticker]
        if price is None:
            continue

        hit = (o["direction"] == "above" and price >= o["trigger_price"]) or \
              (o["direction"] == "below" and price <= o["trigger_price"])
        if not hit:
            continue

        fill_price = o["trigger_price"] if o.get("order_type") == "limit" else None
        try:
            order = place_market_order(o["user_id"], ticker, o["side"], o["lots"], fill_price)
            mark_stock_conditional_order_triggered(o["id"])
            results.append({**o, "result": "triggered", "fill_price": order["price"],
                             "realized_pl": order.get("realized_pl")})
        except PaperTradingError as e:
            mark_stock_conditional_order_failed(o["id"], str(e))
            results.append({**o, "result": "failed", "fail_reason": str(e)})

    return results
