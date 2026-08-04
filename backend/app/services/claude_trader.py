"""Claude 自動選股交易：長期投資／短期交易兩個獨立模擬帳戶，規則全自動、公開透明，
每筆單都記錄「為什麼」，讓使用者可以直接觀察學習。規則會依實際績效定期調整（短期訊號
來源勝率調整下單權重、長期門檻季度回顧），但不會有即時 LLM 判斷成本——全部是排程跑
固定規則，只是規則的參數會隨時間根據追蹤到的真實績效自我調整。
"""
import secrets
from datetime import date, timedelta

from app.db import (
    get_user_by_username, create_user, get_or_create_paper_account, update_paper_cash,
    get_all_db_tickers_with_meta, get_all_latest_fundamentals, get_candles,
    get_claude_strategy_config, save_claude_strategy_config,
)
from app.services.paper_trading import (
    place_market_order, get_positions_with_price, get_order_history,
    get_account_summary, get_performance_stats,
)
from app.services.signal_tracking import get_scan_signal_stats

LONGTERM_USERNAME  = "claude_longterm"
SHORTTERM_USERNAME = "claude_shortterm"
INITIAL_CASH = 1_000_000

LT_MIN_VOLUME_ZHANG = 500   # 長期投資流動性門檻：最近一天成交量至少500張

SCAN_SOURCE_LABEL = {
    "volume_breakout":      "量價突破",
    "institutional_buying": "法人連買",
    "ema60_breakout":       "EMA60貼線噴出",
}

DEFAULT_CONFIG = {
    "lt_max_pe":          15.0,
    "lt_min_div_yield":   4.0,
    "lt_target_holdings": 10,
    "st_position_pct":    0.07,
    "st_stop_loss_pct":   -6.0,
    "st_max_hold_days":   20,
    "st_max_positions":   12,
    "st_scan_weights":    {"volume_breakout": 1.0, "institutional_buying": 1.0, "ema60_breakout": 1.0},
    "last_shortterm_review_month":    None,
    "last_longterm_rebalance_month":  None,
    "last_longterm_quarterly_review": None,
}


def _get_config() -> dict:
    cfg = get_claude_strategy_config() or {}
    merged = {**DEFAULT_CONFIG, **cfg}
    merged["st_scan_weights"] = {**DEFAULT_CONFIG["st_scan_weights"], **cfg.get("st_scan_weights", {})}
    return merged


def _ensure_user(username: str) -> tuple[int, bool]:
    """回傳 (user_id, 是否剛建立)。系統帳號用隨機密碼，不給登入用。"""
    user = get_user_by_username(username)
    if user:
        return user["id"], False
    from app.routers.auth import _hash_password
    user_id = create_user(username, _hash_password(secrets.token_hex(32)))
    return user_id, True


def ensure_claude_accounts() -> tuple[int, int]:
    """確保長期/短期兩個帳戶都存在，剛建立的話給預設本金。回傳 (長期user_id, 短期user_id)。"""
    lt_id, lt_new = _ensure_user(LONGTERM_USERNAME)
    st_id, st_new = _ensure_user(SHORTTERM_USERNAME)
    get_or_create_paper_account(lt_id)
    get_or_create_paper_account(st_id)
    if lt_new:
        update_paper_cash(lt_id, INITIAL_CASH)
    if st_new:
        update_paper_cash(st_id, INITIAL_CASH)
    return lt_id, st_id


# ── 短期交易：每日進場／出場 ──────────────────────────────────

def _shortterm_reason(scan_type: str, hit: dict) -> str:
    label = SCAN_SOURCE_LABEL.get(scan_type, scan_type)
    if scan_type == "volume_breakout":
        return f"{label}：今日量為近5日均量 {hit.get('vol_ratio')} 倍，收盤創20日新高"
    if scan_type == "institutional_buying":
        return f"{label}：外資+投信連續 {hit.get('streak_days')} 天買超，合計 {hit.get('total_net_zhang')} 張"
    if scan_type == "ema60_breakout":
        return f"{label}：{'、'.join(hit.get('reasons', []))}"
    return label


def run_shortterm_daily(scan_hits: dict[str, list]) -> list[dict]:
    """每天排程呼叫：scan_hits 是當天已經跑過的掃描結果
    {"volume_breakout": [...], "institutional_buying": [...], "ema60_breakout": [...]}，
    不用重新掃一次。依訊號來源目前的權重決定要不要進場（權重0＝該來源暫停使用），
    已持有的不重複買，短期倉位數達上限就不再開新倉。
    """
    cfg = _get_config()
    user_id = ensure_claude_accounts()[1]
    account = get_account_summary(user_id)
    positions = get_positions_with_price(user_id)
    held_tickers = {p["ticker"] for p in positions}

    entries = []
    if len(held_tickers) >= cfg["st_max_positions"]:
        return entries

    weights = cfg["st_scan_weights"]
    for scan_type in sorted(scan_hits.keys(), key=lambda t: weights.get(t, 1.0), reverse=True):
        weight = weights.get(scan_type, 1.0)
        if weight <= 0:
            continue
        for hit in scan_hits.get(scan_type) or []:
            if len(held_tickers) >= cfg["st_max_positions"]:
                break
            ticker = hit.get("ticker")
            if not ticker or ticker in held_tickers:
                continue
            price = hit.get("close") or hit.get("entry_price")
            if not price:
                continue
            budget = account["equity"] * cfg["st_position_pct"] * min(weight, 1.5)
            lots = int(budget // (price * 1000))
            if lots <= 0:
                continue
            reason = _shortterm_reason(scan_type, hit)
            try:
                order = place_market_order(user_id, ticker, "buy", lots, reason=reason)
                held_tickers.add(ticker)
                entries.append({"ticker": ticker, "name": hit.get("name"), "lots": lots,
                                 "price": order["price"], "reason": reason})
            except Exception as e:
                print(f"[Claude短期] 買進 {ticker} 失敗: {e}")
    return entries


def run_shortterm_exits() -> list[dict]:
    """每天排程呼叫：檢查短期帳戶持股，觸及停損或滿最大持有天數就出場。"""
    cfg = _get_config()
    user_id = ensure_claude_accounts()[1]
    positions = get_positions_with_price(user_id)
    if not positions:
        return []

    orders = get_order_history(user_id, limit=500)
    first_buy_ts = {}
    for o in reversed(orders):  # orders 新到舊，反過來變舊到新，取第一次出現的買進時間＝進場時間
        if o["side"] == "buy" and o["ticker"] not in first_buy_ts:
            first_buy_ts[o["ticker"]] = o["created_at"]

    today_str = date.today().strftime("%Y-%m-%d")
    exits = []
    for p in positions:
        ticker = p["ticker"]
        reason = None
        if p.get("return_pct") is not None and p["return_pct"] <= cfg["st_stop_loss_pct"]:
            reason = f"觸發停損（報酬率 {p['return_pct']}%）"
        else:
            entry_ts = first_buy_ts.get(ticker)
            if entry_ts is None:
                continue
            entry_date = date.fromtimestamp(entry_ts).strftime("%Y-%m-%d")
            candles = get_candles(ticker, entry_date, today_str)
            trading_days_held = max(0, len(candles) - 1)
            if trading_days_held >= cfg["st_max_hold_days"]:
                reason = f"持有滿 {trading_days_held} 個交易日，依規則出場"
        if not reason:
            continue
        try:
            order = place_market_order(user_id, ticker, "sell", p["lots"], reason=reason)
            exits.append({"ticker": ticker, "name": p.get("name"), "lots": p["lots"],
                          "price": order["price"], "reason": reason, "realized_pl": order.get("realized_pl")})
        except Exception as e:
            print(f"[Claude短期] 賣出 {ticker} 失敗: {e}")
    return exits


def run_shortterm_monthly_review() -> dict | None:
    """每月第一次執行 daily_update 時跑一次：用近90天各訊號來源、已滿20個交易日可評估的
    訊號，統計勝率，調整下個月的下單權重。0＝暫停該來源，0.5＝縮小倉位，1.5＝加碼。
    樣本數太少（<5筆）就維持原權重，避免用太少資料亂調。
    """
    this_month = date.today().strftime("%Y-%m")
    cfg = _get_config()
    if cfg.get("last_shortterm_review_month") == this_month:
        return None

    since = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    new_weights = {}
    summary = {}
    for scan_type in SCAN_SOURCE_LABEL:
        rows = get_scan_signal_stats(scan_type, since)
        if len(rows) < 5:
            new_weights[scan_type] = cfg["st_scan_weights"].get(scan_type, 1.0)
            continue
        win = sum(1 for r in rows if r["return_20d"] is not None and r["return_20d"] > 0)
        win_rate = win / len(rows) * 100
        weight = 0.0 if win_rate < 40 else (0.5 if win_rate < 55 else 1.5)
        new_weights[scan_type] = weight
        summary[scan_type] = {"count": len(rows), "win_rate": round(win_rate, 1), "weight": weight}

    cfg["st_scan_weights"] = new_weights
    cfg["last_shortterm_review_month"] = this_month
    save_claude_strategy_config(cfg)
    return summary


# ── 長期投資：月度換股、季度門檻回顧 ──────────────────────────

def _stock_trend_and_liquidity(ticker: str) -> tuple[float, float] | None:
    """回傳 (收盤價, EMA60) 前提是流動性足夠、資料夠、且站上EMA60；不符合就回傳 None。"""
    from_date = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
    to_date   = date.today().strftime("%Y-%m-%d")
    records = get_candles(ticker, from_date, to_date)
    if not records or len(records) < 62:
        return None
    last_vol_zhang = (records[-1].get("volume") or 0) / 1000
    if last_vol_zhang < LT_MIN_VOLUME_ZHANG:
        return None
    closes = [r["close"] for r in records if r["close"] is not None]
    k, ema = 2 / 61, None
    for c in closes:
        ema = c if ema is None else c * k + ema * (1 - k)
    close = closes[-1]
    if not close or not ema or close <= ema:
        return None
    return close, round(ema, 2)


def _screen_longterm_candidates(cfg: dict) -> list[dict]:
    """本益比 < 門檻、殖利率 > 門檻、站上EMA60、流動性足夠，三個條件都符合才入選。"""
    fundamentals = get_all_latest_fundamentals()
    candidates = []
    for row in get_all_db_tickers_with_meta():
        ticker = row["ticker"]
        if row.get("parent_industry") == "金融保險":
            continue
        fund = fundamentals.get(ticker)
        if not fund or not fund.get("pe_ratio") or not fund.get("dividend_yield"):
            continue
        if fund["pe_ratio"] <= 0 or fund["pe_ratio"] > cfg["lt_max_pe"]:
            continue
        if fund["dividend_yield"] < cfg["lt_min_div_yield"]:
            continue
        trend = _stock_trend_and_liquidity(ticker)
        if not trend:
            continue
        close, ema60 = trend
        score = fund["dividend_yield"] - fund["pe_ratio"] / 5
        candidates.append({
            "ticker": ticker, "name": row.get("name") or "",
            "pe_ratio": fund["pe_ratio"], "dividend_yield": fund["dividend_yield"],
            "close": close, "ema60": ema60, "score": score,
        })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def run_longterm_rebalance() -> dict | None:
    """每月第一次執行 daily_update 時跑一次：不再符合條件的持股賣出，新入選的等權重買進。"""
    this_month = date.today().strftime("%Y-%m")
    cfg = _get_config()
    if cfg.get("last_longterm_rebalance_month") == this_month:
        return None

    user_id = ensure_claude_accounts()[0]
    candidates = _screen_longterm_candidates(cfg)
    target = candidates[:cfg["lt_target_holdings"]]
    target_map = {c["ticker"]: c for c in target}
    target_tickers = set(target_map.keys())

    positions = get_positions_with_price(user_id)
    held_tickers = {p["ticker"] for p in positions}

    sold, bought = [], []
    for p in positions:
        if p["ticker"] in target_tickers:
            continue
        try:
            reason = "月度重新篩選：不再符合長期投資條件（本益比／殖利率／站上EMA60其中一項不符）"
            order = place_market_order(user_id, p["ticker"], "sell", p["lots"], reason=reason)
            sold.append({"ticker": p["ticker"], "name": p.get("name"), "realized_pl": order.get("realized_pl")})
        except Exception as e:
            print(f"[Claude長期] 賣出 {p['ticker']} 失敗: {e}")

    new_tickers = [t for t in target_tickers if t not in held_tickers]
    if new_tickers:
        account = get_account_summary(user_id)
        budget_each = account["equity"] / cfg["lt_target_holdings"]
        for ticker in new_tickers:
            c = target_map[ticker]
            lots = int(budget_each // (c["close"] * 1000))
            if lots <= 0:
                continue
            try:
                reason = (f"長期投資選股：本益比 {c['pe_ratio']}、殖利率 {c['dividend_yield']}%、"
                          f"站上EMA60（現價 {c['close']} > EMA60 {c['ema60']}）")
                order = place_market_order(user_id, ticker, "buy", lots, reason=reason)
                bought.append({"ticker": ticker, "name": c["name"], "lots": lots, "price": order["price"]})
            except Exception as e:
                print(f"[Claude長期] 買進 {ticker} 失敗: {e}")

    cfg["last_longterm_rebalance_month"] = this_month
    save_claude_strategy_config(cfg)
    return {"sold": sold, "bought": bought, "candidates_found": len(candidates)}


def run_longterm_quarterly_review() -> dict | None:
    """每季第一次執行時跑一次：檢視近期已平倉交易的整體勝率，數據顯示門檻太鬆（勝率低）
    就收緊，太嚴（勝率極高，可能篩選過頭、候選池太小）就適度放寬，在合理範圍內微調。
    """
    q = (date.today().month - 1) // 3 + 1
    this_quarter = f"{date.today().year}-Q{q}"
    cfg = _get_config()
    if cfg.get("last_longterm_quarterly_review") == this_quarter:
        return None

    user_id = ensure_claude_accounts()[0]
    stats = get_performance_stats(user_id)
    adjustment = None
    if stats["total_trades"] >= 5 and stats["win_rate"] is not None:
        if stats["win_rate"] < 40:
            cfg["lt_max_pe"] = max(8.0, round(cfg["lt_max_pe"] - 1, 1))
            cfg["lt_min_div_yield"] = min(8.0, round(cfg["lt_min_div_yield"] + 0.5, 1))
            adjustment = "門檻收緊（近期勝率偏低）"
        elif stats["win_rate"] > 70:
            cfg["lt_max_pe"] = min(25.0, round(cfg["lt_max_pe"] + 1, 1))
            cfg["lt_min_div_yield"] = max(2.0, round(cfg["lt_min_div_yield"] - 0.5, 1))
            adjustment = "門檻放寬（近期勝率很高，適度擴大候選池）"

    cfg["last_longterm_quarterly_review"] = this_quarter
    save_claude_strategy_config(cfg)
    return {
        "stats": stats, "adjustment": adjustment,
        "new_max_pe": cfg["lt_max_pe"], "new_min_div_yield": cfg["lt_min_div_yield"],
    }


# ── 顯示用 ──────────────────────────────────────────────────

def get_claude_portfolio(strategy: str) -> dict:
    """strategy: "longterm" 或 "shortterm"。回傳帳戶摘要、持股(含最近一次買進理由)、成交紀錄。"""
    username = LONGTERM_USERNAME if strategy == "longterm" else SHORTTERM_USERNAME
    user = get_user_by_username(username)
    if not user:
        return {"account": None, "positions": [], "orders": []}

    user_id = user["id"]
    account = get_account_summary(user_id)
    positions = get_positions_with_price(user_id)
    orders = get_order_history(user_id, limit=200)

    latest_buy_reason = {}
    for o in orders:  # 新到舊，第一次遇到某ticker的買進單就是目前持股的理由
        if o["side"] == "buy" and o["ticker"] not in latest_buy_reason:
            latest_buy_reason[o["ticker"]] = o.get("reason")
    for p in positions:
        p["reason"] = latest_buy_reason.get(p["ticker"])

    return {"account": account, "positions": positions, "orders": orders[:50]}


def get_claude_strategy_summary() -> dict:
    """回傳目前生效的策略參數，供前端顯示透明度用。"""
    return _get_config()
