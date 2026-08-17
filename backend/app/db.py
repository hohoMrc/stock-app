import json
import sqlite3
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent.parent / "stock_cache.db"

_local = threading.local()


def _conn() -> sqlite3.Connection:
    """每個 thread 重用同一個 SQLite 連線，避免 fd 耗盡。"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    REAL
        );

        CREATE TABLE IF NOT EXISTS watchlists (
            user_id     INTEGER NOT NULL,
            ticker      TEXT NOT NULL,
            note        TEXT DEFAULT '',
            added_at    REAL,
            PRIMARY KEY (user_id, ticker),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS stock_meta (
            ticker          TEXT PRIMARY KEY,
            name            TEXT,
            industry        TEXT,
            parent_industry TEXT,
            exchange        TEXT,
            updated_at      REAL
        );

        CREATE TABLE IF NOT EXISTS candles (
            ticker  TEXT NOT NULL,
            date    TEXT NOT NULL,
            open    REAL,
            high    REAL,
            low     REAL,
            close   REAL,
            volume  INTEGER,
            PRIMARY KEY (ticker, date)
        );

        CREATE INDEX IF NOT EXISTS idx_candles_ticker
            ON candles(ticker, date DESC);

        CREATE TABLE IF NOT EXISTS institutional_trades (
            ticker      TEXT NOT NULL,
            date        TEXT NOT NULL,
            foreign_net INTEGER,
            trust_net   INTEGER,
            dealer_net  INTEGER,
            total_net   INTEGER,
            PRIMARY KEY (ticker, date)
        );

        CREATE INDEX IF NOT EXISTS idx_institutional_ticker
            ON institutional_trades(ticker, date DESC);

        CREATE TABLE IF NOT EXISTS fundamentals (
            ticker         TEXT NOT NULL,
            date           TEXT NOT NULL,
            pe_ratio       REAL,
            dividend_yield REAL,
            pb_ratio       REAL,
            PRIMARY KEY (ticker, date)
        );

        CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker
            ON fundamentals(ticker, date DESC);

        CREATE TABLE IF NOT EXISTS margin_trading (
            ticker         TEXT NOT NULL,
            date           TEXT NOT NULL,
            margin_balance INTEGER,
            margin_quota   INTEGER,
            short_balance  INTEGER,
            short_quota    INTEGER,
            PRIMARY KEY (ticker, date)
        );

        CREATE INDEX IF NOT EXISTS idx_margin_trading_ticker
            ON margin_trading(ticker, date DESC);

        CREATE TABLE IF NOT EXISTS scan_signals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker        TEXT NOT NULL,
            name          TEXT,
            scan_type     TEXT NOT NULL,
            signal_date   TEXT NOT NULL,
            signal_price  REAL,
            return_5d     REAL,
            return_10d    REAL,
            return_20d    REAL,
            UNIQUE(ticker, scan_type, signal_date)
        );

        CREATE INDEX IF NOT EXISTS idx_scan_signals_pending
            ON scan_signals(return_20d, signal_date);
        CREATE INDEX IF NOT EXISTS idx_scan_signals_type
            ON scan_signals(scan_type, signal_date);

        CREATE TABLE IF NOT EXISTS ema60_watchlist (
            ticker          TEXT PRIMARY KEY,
            name            TEXT,
            first_seen_date TEXT NOT NULL,
            last_seen_date  TEXT NOT NULL,
            entry_price     REAL
        );

        CREATE TABLE IF NOT EXISTS ema60_watch_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            name        TEXT,
            event_type  TEXT NOT NULL,
            reason      TEXT,
            event_date  TEXT NOT NULL,
            created_at  REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ema60_watch_events_date
            ON ema60_watch_events(event_date);

        CREATE TABLE IF NOT EXISTS warrants (
            ticker            TEXT PRIMARY KEY,
            name              TEXT,
            underlying_ticker TEXT,
            underlying_name   TEXT,
            issuer_name       TEXT,
            issue_date        TEXT,
            updated_at        REAL
        );

        CREATE INDEX IF NOT EXISTS idx_warrants_underlying
            ON warrants(underlying_ticker, issue_date DESC);

        CREATE TABLE IF NOT EXISTS futures_candles (
            symbol    TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            time      INTEGER NOT NULL,
            open      REAL,
            high      REAL,
            low       REAL,
            close     REAL,
            volume    INTEGER,
            PRIMARY KEY (symbol, timeframe, time)
        );

        CREATE INDEX IF NOT EXISTS idx_futures_candles
            ON futures_candles(symbol, timeframe, time DESC);

        CREATE TABLE IF NOT EXISTS paper_accounts (
            user_id    INTEGER PRIMARY KEY,
            cash       REAL NOT NULL,
            created_at REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS paper_positions (
            user_id  INTEGER NOT NULL,
            ticker   TEXT NOT NULL,
            qty      INTEGER NOT NULL,
            avg_cost REAL NOT NULL,
            PRIMARY KEY (user_id, ticker),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS paper_orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            ticker      TEXT NOT NULL,
            name        TEXT,
            side        TEXT NOT NULL,
            qty         INTEGER NOT NULL,
            price       REAL NOT NULL,
            fee         REAL NOT NULL,
            tax         REAL NOT NULL,
            net_amount  REAL NOT NULL,
            realized_pl REAL,
            created_at  REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_paper_orders_user
            ON paper_orders(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS paper_futures_accounts (
            user_id    INTEGER PRIMARY KEY,
            cash       REAL NOT NULL,
            created_at REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS paper_futures_positions (
            user_id        INTEGER NOT NULL,
            product        TEXT NOT NULL,
            side           TEXT NOT NULL,
            qty            INTEGER NOT NULL,
            avg_price      REAL NOT NULL,
            open_fee_total REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, product),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS paper_futures_orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            product     TEXT NOT NULL,
            side        TEXT NOT NULL,
            action      TEXT NOT NULL,
            qty         INTEGER NOT NULL,
            price       REAL NOT NULL,
            open_price  REAL,
            fee         REAL NOT NULL,
            tax         REAL NOT NULL,
            net_amount  REAL NOT NULL,
            realized_pl REAL,
            created_at  REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_paper_futures_orders_user
            ON paper_futures_orders(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS price_alerts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            ticker       TEXT NOT NULL,
            alert_type   TEXT NOT NULL,
            target_price REAL,
            scan_type    TEXT,
            active       INTEGER NOT NULL DEFAULT 1,
            triggered_at REAL,
            created_at   REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_price_alerts_user
            ON price_alerts(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_price_alerts_ticker
            ON price_alerts(ticker);

        CREATE TABLE IF NOT EXISTS paper_futures_conditional_orders (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            product       TEXT NOT NULL,
            side          TEXT NOT NULL,
            action        TEXT NOT NULL,
            qty           INTEGER NOT NULL,
            trigger_price REAL NOT NULL,
            direction     TEXT NOT NULL,
            order_type    TEXT NOT NULL DEFAULT 'stop',
            status        TEXT NOT NULL DEFAULT 'pending',
            fail_reason   TEXT,
            created_at    REAL,
            triggered_at  REAL,
            user_note     TEXT DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_pfco_pending
            ON paper_futures_conditional_orders(status, product);

        CREATE TABLE IF NOT EXISTS paper_conditional_orders (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            ticker        TEXT NOT NULL,
            side          TEXT NOT NULL,
            lots          INTEGER NOT NULL,
            trigger_price REAL NOT NULL,
            direction     TEXT NOT NULL,
            order_type    TEXT NOT NULL DEFAULT 'stop',
            status        TEXT NOT NULL DEFAULT 'pending',
            fail_reason   TEXT,
            created_at    REAL,
            triggered_at  REAL,
            user_note     TEXT DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_pco_pending
            ON paper_conditional_orders(status);

        CREATE TABLE IF NOT EXISTS news_summaries (
            date             TEXT PRIMARY KEY,
            summary          TEXT NOT NULL,
            stock_watch_json TEXT NOT NULL DEFAULT '[]',
            created_at       REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS claude_strategy_config (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            config_json TEXT NOT NULL,
            updated_at  REAL NOT NULL
        );
        """)
        # Migration: 舊版 DB 沒有 parent_industry 欄位
        try:
            conn.execute("ALTER TABLE stock_meta ADD COLUMN parent_industry TEXT")
        except Exception:
            pass
        # Migration: 舊版 watchlists 沒有 note 欄位
        try:
            conn.execute("ALTER TABLE watchlists ADD COLUMN note TEXT DEFAULT ''")
        except Exception:
            pass
        # Migration: 智慧單新增訂單類型（stop=觸價後市價成交／原本的行為，limit=用設定價格成交）
        try:
            conn.execute("ALTER TABLE paper_futures_conditional_orders ADD COLUMN order_type TEXT NOT NULL DEFAULT 'stop'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE paper_conditional_orders ADD COLUMN order_type TEXT NOT NULL DEFAULT 'stop'")
        except Exception:
            pass
        # Migration: 股票模擬下單成交紀錄加「理由」欄位（Claude自動交易用，記錄為什麼下這筆單）
        try:
            conn.execute("ALTER TABLE paper_orders ADD COLUMN reason TEXT")
        except Exception:
            pass
        # Migration: 智慧單加使用者可自行輸入的備註欄位（跟系統的 fail_reason 分開）
        try:
            conn.execute("ALTER TABLE paper_futures_conditional_orders ADD COLUMN user_note TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE paper_conditional_orders ADD COLUMN user_note TEXT DEFAULT ''")
        except Exception:
            pass
        # Migration: 期貨部位加「累積未結算開倉手續費」欄位（建倉先不記一筆成交紀錄，
        # 等平倉時才把開倉+平倉手續費合併記一筆，減少歷史成交紀錄的筆數）
        try:
            conn.execute("ALTER TABLE paper_futures_positions ADD COLUMN open_fee_total REAL NOT NULL DEFAULT 0")
        except Exception:
            pass
        # Migration: 新聞摘要加「台股觀察個股清單」欄位（改用鉅亨網後直接用新聞自帶關聯個股，不用AI猜）
        try:
            conn.execute("ALTER TABLE news_summaries ADD COLUMN stock_watch_json TEXT NOT NULL DEFAULT '[]'")
        except Exception:
            pass
        # Migration: 期貨成交紀錄加「成本價」欄位（平倉那筆紀錄順便存當初的建倉均價，
        # 不然只看得到平倉價跟已實現損益，看不出這趟交易的成本是多少）
        try:
            conn.execute("ALTER TABLE paper_futures_orders ADD COLUMN open_price REAL")
        except Exception:
            pass


# ── stock_meta ──────────────────────────────────────────

def get_stock_meta(ticker: str, max_age_hours: float = 168) -> dict | None:
    """回傳快取的股票基本資料，預設 7 天內有效。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT name, industry, exchange, updated_at FROM stock_meta WHERE ticker=?",
            (ticker,)
        ).fetchone()
    if not row:
        return None
    if time.time() - row["updated_at"] > max_age_hours * 3600:
        return None
    return {"name": row["name"], "industry": row["industry"], "exchange": row["exchange"]}


def save_stock_meta(ticker: str, name: str | None, industry: str | None, exchange: str | None,
                    parent_industry: str | None = None):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO stock_meta(ticker, name, industry, parent_industry, exchange, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            "name=excluded.name, industry=excluded.industry, exchange=excluded.exchange, "
            "updated_at=excluded.updated_at, "
            "parent_industry=COALESCE(excluded.parent_industry, stock_meta.parent_industry)",
            (ticker, name, industry, parent_industry, exchange, time.time())
        )


def bulk_save_stock_meta(records: list[tuple]):
    """批次寫入 (ticker, name, industry, parent_industry, exchange)，強制更新。"""
    now = time.time()
    with _conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO stock_meta"
            "(ticker, name, industry, parent_industry, exchange, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(t, n, i, p, e, now) for t, n, i, p, e in records]
        )


def get_parent_industry(ticker: str) -> str | None:
    """回傳 ticker 在 stock_meta 裡的 parent_industry（TWSE 大分類）。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT parent_industry FROM stock_meta WHERE ticker=?", (ticker,)
        ).fetchone()
    return row["parent_industry"] if row else None


def _get_parent_from_industry(industry: str) -> str | None:
    """從同一 industry 的任一筆取得 parent_industry（不需要 ticker）。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT parent_industry FROM stock_meta WHERE industry=? AND parent_industry IS NOT NULL LIMIT 1",
            (industry,)
        ).fetchone()
    return row["parent_industry"] if row else None


def get_all_db_tickers() -> list[str]:
    """回傳 stock_meta 中所有有 K 線資料的 ticker。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM candles ORDER BY ticker"
        ).fetchall()
    return [r["ticker"] for r in rows]


def get_all_db_tickers_with_meta() -> list[dict]:
    """回傳所有有 K 線的 ticker 及其 name、exchange、parent_industry。"""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT c.ticker, m.name, m.exchange, m.parent_industry
            FROM (SELECT DISTINCT ticker FROM candles) c
            LEFT JOIN stock_meta m ON c.ticker = m.ticker
            ORDER BY c.ticker
        """).fetchall()
    return [dict(r) for r in rows]


def get_tickers_by_industry(industry: str, exclude_ticker: str | None = None) -> list[str]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker FROM stock_meta WHERE industry=? AND ticker!=? ORDER BY ticker",
            (industry, exclude_ticker or "")
        ).fetchall()
    return [r["ticker"] for r in rows]


def get_industry_stocks_with_price(industry: str, exclude_ticker: str | None = None,
                                   limit: int = 40, use_parent: bool = False) -> list[dict]:
    """從 DB 直接回傳同產業股票 + 最新收盤價，不打外部 API。
    use_parent=True 時改查 parent_industry 欄位（大分類）。
    """
    col = "parent_industry" if use_parent else "industry"
    with _conn() as conn:
        rows = conn.execute(f"""
            SELECT m.ticker, m.name, m.exchange, m.industry,
                   c.close AS price, c.date AS price_date
            FROM stock_meta m
            LEFT JOIN (
                SELECT ticker, close, date
                FROM candles
                WHERE (ticker, date) IN (
                    SELECT ticker, MAX(date) FROM candles GROUP BY ticker
                )
            ) c ON m.ticker = c.ticker
            WHERE m.{col} = ? AND m.ticker != ?
            ORDER BY c.close DESC
            LIMIT ?
        """, (industry, exclude_ticker or "", limit)).fetchall()
    return [dict(r) for r in rows]


# ── candles ─────────────────────────────────────────────

def get_all_candles_in_range(from_date: str, to_date: str) -> dict[str, list[dict]]:
    """一次取出所有 ticker 在日期範圍內的 K 線，回傳 {ticker: [candle,...]}。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, date, close, volume FROM candles "
            "WHERE date>=? AND date<=? ORDER BY ticker, date",
            (from_date, to_date)
        ).fetchall()
    result: dict[str, list] = {}
    for r in rows:
        d = dict(r)
        result.setdefault(d["ticker"], []).append(d)
    return result


def get_candles(ticker: str, from_date: str, to_date: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM candles "
            "WHERE ticker=? AND date>=? AND date<=? ORDER BY date",
            (ticker, from_date, to_date)
        ).fetchall()
    return [dict(r) for r in rows]


def save_candles(ticker: str, records: list[dict]):
    if not records:
        return
    with _conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO candles(ticker, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (ticker, r["date"], r.get("open"), r.get("high"),
                 r.get("low"), r.get("close"), r.get("volume"))
                for r in records if r.get("date")
            ]
        )


def is_candles_fresh(ticker: str, from_date: str, to_date: str) -> bool:
    """判斷 DB 裡的 K 線是否夠新（最新一筆在 3 個自然日內）。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT MAX(date) as latest FROM candles WHERE ticker=? AND date>=? AND date<=?",
            (ticker, from_date, to_date)
        ).fetchone()
    if not row or not row["latest"]:
        return False
    latest = datetime.strptime(row["latest"], "%Y-%m-%d").date()
    return (datetime.now().date() - latest).days <= 3


# ── institutional_trades（三大法人買賣超）─────────────────

def save_institutional_trades(records: list[dict]):
    if not records:
        return
    with _conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO institutional_trades"
            "(ticker, date, foreign_net, trust_net, dealer_net, total_net) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (r["ticker"], r["date"], r.get("foreign_net"),
                 r.get("trust_net"), r.get("dealer_net"), r.get("total_net"))
                for r in records if r.get("ticker") and r.get("date")
            ]
        )


def get_all_institutional_trades_in_range(from_date: str, to_date: str) -> dict[str, list[dict]]:
    """一次取出所有 ticker 在日期範圍內的三大法人買賣超，回傳 {ticker: [record,...]}（依日期由舊到新）。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, date, foreign_net, trust_net, dealer_net, total_net "
            "FROM institutional_trades WHERE date>=? AND date<=? ORDER BY ticker, date",
            (from_date, to_date)
        ).fetchall()
    result: dict[str, list] = {}
    for r in rows:
        result.setdefault(r["ticker"], []).append(dict(r))
    return result


def get_institutional_trades_for_ticker(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """取單一股票在日期範圍內的三大法人買賣超（依日期由舊到新）。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT date, foreign_net, trust_net, dealer_net, total_net "
            "FROM institutional_trades WHERE ticker=? AND date>=? AND date<=? ORDER BY date",
            (ticker, from_date, to_date)
        ).fetchall()
    return [dict(r) for r in rows]


# ── fundamentals（本益比/殖利率/股價淨值比）────────────────

def save_fundamentals(records: list[dict]):
    if not records:
        return
    with _conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO fundamentals"
            "(ticker, date, pe_ratio, dividend_yield, pb_ratio) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (r["ticker"], r["date"], r.get("pe_ratio"), r.get("dividend_yield"), r.get("pb_ratio"))
                for r in records if r.get("ticker") and r.get("date")
            ]
        )


def get_all_latest_fundamentals() -> dict[str, dict]:
    """一次取出全市場各 ticker 最新一筆基本面資料，供 screen_stocks 全市場掃描用。"""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT f.ticker, f.pe_ratio, f.dividend_yield, f.pb_ratio
            FROM fundamentals f
            INNER JOIN (
                SELECT ticker, MAX(date) AS max_date FROM fundamentals GROUP BY ticker
            ) latest ON f.ticker = latest.ticker AND f.date = latest.max_date
        """).fetchall()
    return {r["ticker"]: dict(r) for r in rows}


def get_latest_fundamentals(ticker: str) -> dict | None:
    """取單一股票最新一筆基本面資料，供個股頁用。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT pe_ratio, dividend_yield, pb_ratio FROM fundamentals "
            "WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,)
        ).fetchone()
    return dict(row) if row else None


# ── margin_trading（融資融券）───────────────────────────────

def save_margin_trading(records: list[dict]):
    if not records:
        return
    with _conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO margin_trading"
            "(ticker, date, margin_balance, margin_quota, short_balance, short_quota) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (r["ticker"], r["date"], r.get("margin_balance"), r.get("margin_quota"),
                 r.get("short_balance"), r.get("short_quota"))
                for r in records if r.get("ticker") and r.get("date")
            ]
        )


def get_latest_margin_trading(ticker: str) -> dict | None:
    """取單一股票最新一筆融資融券資料，供個股頁用。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT margin_balance, margin_quota, short_balance, short_quota FROM margin_trading "
            "WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,)
        ).fetchone()
    return dict(row) if row else None


# ── scan_signals（快速篩選訊號成效追蹤）───────────────────

def save_scan_signals(records: list[dict]):
    """記錄快篩命中的股票快照。INSERT OR IGNORE：同股票同篩選同天已存在就不重複寫入。"""
    if not records:
        return
    with _conn() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO scan_signals"
            "(ticker, name, scan_type, signal_date, signal_price) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (r["ticker"], r.get("name", ""), r["scan_type"], r["signal_date"], r.get("signal_price"))
                for r in records if r.get("ticker") and r.get("scan_type") and r.get("signal_date")
            ]
        )


def get_signals_pending_evaluation(limit: int = 500) -> list[dict]:
    """撈還沒算出 20 日報酬率的訊號（不論訊號日多久以前，實際夠不夠交易日由呼叫端用K棒數判斷）。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, ticker, scan_type, signal_date, signal_price FROM scan_signals "
            "WHERE return_20d IS NULL ORDER BY signal_date LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_signal_returns(signal_id: int, return_5d: float | None, return_10d: float | None, return_20d: float | None):
    """只更新算得出來的欄位（傳 None 的欄位維持原值），因為 5/10/20 日往往不是同時到達。"""
    with _conn() as conn:
        conn.execute(
            "UPDATE scan_signals SET "
            "return_5d=COALESCE(?, return_5d), "
            "return_10d=COALESCE(?, return_10d), "
            "return_20d=COALESCE(?, return_20d) "
            "WHERE id=?",
            (return_5d, return_10d, return_20d, signal_id)
        )


def get_scan_signal_stats(scan_type: str, since_date: str) -> list[dict]:
    """撈某篩選類型、20日報酬率已算出（代表可完整評估）的訊號，供統計勝率/平均報酬用。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, name, signal_date, signal_price, return_5d, return_10d, return_20d "
            "FROM scan_signals WHERE scan_type=? AND signal_date>=? AND return_20d IS NOT NULL "
            "ORDER BY signal_date",
            (scan_type, since_date)
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_scan_signals(scan_type: str, since_date: str, limit: int = 100) -> list[dict]:
    """撈某篩選類型近期的訊號快照，不論5/10/20日報酬率算出來沒（供「噴出後繼續追蹤」這類
    畫面用，跟 get_scan_signal_stats 不同——那個只看已經滿20個交易日、可完整評估的）。
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, name, signal_date, signal_price, return_5d, return_10d, return_20d "
            "FROM scan_signals WHERE scan_type=? AND signal_date>=? "
            "ORDER BY signal_date DESC LIMIT ?",
            (scan_type, since_date, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# ── ema60_watchlist（EMA60近線候選觀察名單→等噴出訊號）──────

def upsert_ema60_watch(ticker: str, name: str, date_str: str, price: float | None) -> bool:
    """新股票：first_seen/last_seen 都設今天，回傳 True（這次是新加入）。
    已存在：只更新 last_seen（first_seen/entry_price 不變），回傳 False。
    """
    with _conn() as conn:
        existing = conn.execute("SELECT 1 FROM ema60_watchlist WHERE ticker=?", (ticker,)).fetchone()
        conn.execute(
            "INSERT INTO ema60_watchlist(ticker, name, first_seen_date, last_seen_date, entry_price) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET last_seen_date=excluded.last_seen_date",
            (ticker, name, date_str, date_str, price)
        )
    return existing is None


def get_ema60_watchlist() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, name, first_seen_date, last_seen_date, entry_price FROM ema60_watchlist"
        ).fetchall()
    return [dict(r) for r in rows]


def remove_ema60_watch(tickers: list[str]):
    """噴出訊號已觸發，從觀察名單移除（任務結束，不重複通知）。"""
    if not tickers:
        return
    with _conn() as conn:
        conn.executemany("DELETE FROM ema60_watchlist WHERE ticker=?", [(t,) for t in tickers])


def prune_stale_ema60_watch(cutoff_date: str) -> list[dict]:
    """清掉太久沒再出現在EMA60近線名單裡、也一直沒噴出的股票（型態已失效）。回傳被清掉的 {ticker, name} 清單。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, name FROM ema60_watchlist WHERE last_seen_date < ?", (cutoff_date,)
        ).fetchall()
        removed = [dict(r) for r in rows]
        if removed:
            conn.executemany("DELETE FROM ema60_watchlist WHERE ticker=?", [(r["ticker"],) for r in removed])
    return removed


def log_ema60_watch_events(events: list[dict]):
    """記錄觀察名單的加入/移除事件，供週報彙整用。
    events: [{"ticker","name","event_type":"added"/"removed","reason":str|None,"event_date"}]
    """
    if not events:
        return
    with _conn() as conn:
        conn.executemany(
            "INSERT INTO ema60_watch_events(ticker, name, event_type, reason, event_date, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(e["ticker"], e.get("name", ""), e["event_type"], e.get("reason"), e["event_date"], time.time())
             for e in events]
        )


def get_ema60_watch_events(since_date: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, name, event_type, reason, event_date FROM ema60_watch_events "
            "WHERE event_date>=? ORDER BY event_date, ticker",
            (since_date,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── warrants（權證→標的股對照表，每日排程批次更新）──────────

def save_warrants(records: list[dict]):
    """INSERT OR REPLACE：只存最新已知的對照關係，不用像 institutional_trades 存歷史。"""
    if not records:
        return
    with _conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO warrants"
            "(ticker, name, underlying_ticker, underlying_name, issuer_name, issue_date, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (r["ticker"], r.get("name", ""), r.get("underlying_ticker", ""),
                 r.get("underlying_name", ""), r.get("issuer_name", ""), r.get("issue_date", ""),
                 time.time())
                for r in records if r.get("ticker") and r.get("underlying_ticker")
            ]
        )


def get_warrants_by_underlying(ticker: str, limit: int = 80) -> list[dict]:
    """撈某標的股的權證候選（依發行日期新到舊），供個股頁「權證」分頁即時查詢即時資料用。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, name, issuer_name, issue_date FROM warrants "
            "WHERE underlying_ticker=? ORDER BY issue_date DESC LIMIT ?",
            (ticker, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_warrant_by_ticker(ticker: str) -> dict | None:
    """用權證代號本身反查對照表，供「權證查詢」頁判斷輸入的是不是一個已知權證代號。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT ticker, name, underlying_ticker, underlying_name, issuer_name FROM warrants "
            "WHERE ticker=?",
            (ticker,)
        ).fetchone()
    return dict(row) if row else None


# ── futures_candles ─────────────────────────────────────

def save_futures_candles(symbol: str, timeframe: str, candles: list[dict]):
    """存入期貨盤中 K 棒（INSERT OR REPLACE）。"""
    if not candles:
        return
    with _conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO futures_candles"
            "(symbol, timeframe, time, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (symbol, timeframe, c["time"],
                 c.get("open"), c.get("high"), c.get("low"), c.get("close"), c.get("volume", 0))
                for c in candles
            ]
        )


def get_futures_candles_db(symbol: str, timeframe: str, limit: int = 3000) -> list[dict]:
    """從 DB 取期貨歷史 K 棒，由舊到新排序。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT time, open, high, low, close, volume FROM futures_candles "
            "WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT ?",
            (symbol, timeframe, limit)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── users ────────────────────────────────────────────────

def create_user(username: str, password_hash: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, time.time())
        )
        return cur.lastrowid


def get_user_by_username(username: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username=?", (username,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, username FROM users WHERE id=?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def get_all_users() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, username, created_at FROM users ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def update_user_password(user_id: int, password_hash: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (password_hash, user_id)
        )


def delete_user(user_id: int):
    with _conn() as conn:
        conn.execute("DELETE FROM watchlists WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))


# ── watchlists ───────────────────────────────────────────

def get_watchlist(user_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, note, added_at FROM watchlists WHERE user_id=? ORDER BY added_at DESC",
            (user_id,)
        ).fetchall()
    return [{"ticker": r["ticker"], "note": r["note"] or "", "added_at": r["added_at"]} for r in rows]


def update_watchlist_note(user_id: int, ticker: str, note: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE watchlists SET note=? WHERE user_id=? AND ticker=?",
            (note, user_id, ticker)
        )


def add_to_watchlist(user_id: int, ticker: str):
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlists(user_id, ticker, added_at) VALUES (?, ?, ?)",
            (user_id, ticker, time.time())
        )


def remove_from_watchlist(user_id: int, ticker: str):
    with _conn() as conn:
        conn.execute(
            "DELETE FROM watchlists WHERE user_id=? AND ticker=?", (user_id, ticker)
        )


# ── paper trading（模擬下單）──────────────────────────────

PAPER_INITIAL_CASH = 100_000


def get_or_create_paper_account(user_id: int) -> dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT user_id, cash FROM paper_accounts WHERE user_id=?", (user_id,)
        ).fetchone()
        if row:
            return dict(row)
        conn.execute(
            "INSERT INTO paper_accounts(user_id, cash, created_at) VALUES (?, ?, ?)",
            (user_id, PAPER_INITIAL_CASH, time.time())
        )
        return {"user_id": user_id, "cash": PAPER_INITIAL_CASH}


def update_paper_cash(user_id: int, cash: float):
    with _conn() as conn:
        conn.execute(
            "UPDATE paper_accounts SET cash=? WHERE user_id=?", (cash, user_id)
        )


def get_paper_position(user_id: int, ticker: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT ticker, qty, avg_cost FROM paper_positions WHERE user_id=? AND ticker=?",
            (user_id, ticker)
        ).fetchone()
    return dict(row) if row else None


def upsert_paper_position(user_id: int, ticker: str, qty: int, avg_cost: float):
    with _conn() as conn:
        if qty <= 0:
            conn.execute(
                "DELETE FROM paper_positions WHERE user_id=? AND ticker=?", (user_id, ticker)
            )
        else:
            conn.execute(
                "INSERT INTO paper_positions(user_id, ticker, qty, avg_cost) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, ticker) DO UPDATE SET qty=excluded.qty, avg_cost=excluded.avg_cost",
                (user_id, ticker, qty, avg_cost)
            )


def get_paper_positions(user_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, qty, avg_cost FROM paper_positions WHERE user_id=? ORDER BY ticker",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def insert_paper_order(user_id: int, ticker: str, name: str | None, side: str, qty: int,
                        price: float, fee: float, tax: float, net_amount: float,
                        realized_pl: float | None, reason: str | None = None):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO paper_orders"
            "(user_id, ticker, name, side, qty, price, fee, tax, net_amount, realized_pl, created_at, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, ticker, name, side, qty, price, fee, tax, net_amount, realized_pl, time.time(), reason)
        )


def get_paper_orders(user_id: int, limit: int = 50) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, name, side, qty, price, fee, tax, net_amount, realized_pl, created_at, reason "
            "FROM paper_orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# ── claude_strategy_config（Claude自動交易的自適應參數，單一列JSON） ──────

def get_claude_strategy_config() -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT config_json FROM claude_strategy_config WHERE id=1").fetchone()
    if not row:
        return None
    import json
    return json.loads(row["config_json"])


def save_claude_strategy_config(config: dict):
    import json
    with _conn() as conn:
        conn.execute(
            "INSERT INTO claude_strategy_config(id, config_json, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json, updated_at=excluded.updated_at",
            (json.dumps(config), time.time())
        )


def get_paper_realized_pl_total(user_id: int) -> float:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(realized_pl), 0) AS total FROM paper_orders WHERE user_id=?",
            (user_id,)
        ).fetchone()
    return row["total"]


def get_paper_closed_trades(user_id: int) -> list[dict]:
    """取全部已平倉交易（賣出且有 realized_pl 的紀錄），依時間由舊到新，供績效分析用。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, name, qty, price, realized_pl, created_at FROM paper_orders "
            "WHERE user_id=? AND side='sell' AND realized_pl IS NOT NULL ORDER BY created_at ASC",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_paper_bought_qty_since(user_id: int, ticker: str, since_ts: float) -> int:
    """回傳某股票自 since_ts（通常是今日 00:00）以來累計買進的股數，供禁止當沖判斷用。"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS total FROM paper_orders "
            "WHERE user_id=? AND ticker=? AND side='buy' AND created_at>=?",
            (user_id, ticker, since_ts)
        ).fetchone()
    return row["total"]


# ── paper futures trading（期貨模擬下單，跟股票模擬下單分開一個本金）───

PAPER_FUTURES_INITIAL_CASH = 1_500_000  # 大台原始保證金636,000，起始本金要夠開至少1口還有餘裕


def get_or_create_paper_futures_account(user_id: int) -> dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT user_id, cash FROM paper_futures_accounts WHERE user_id=?", (user_id,)
        ).fetchone()
        if row:
            return dict(row)
        conn.execute(
            "INSERT INTO paper_futures_accounts(user_id, cash, created_at) VALUES (?, ?, ?)",
            (user_id, PAPER_FUTURES_INITIAL_CASH, time.time())
        )
        return {"user_id": user_id, "cash": PAPER_FUTURES_INITIAL_CASH}


def update_paper_futures_cash(user_id: int, cash: float):
    with _conn() as conn:
        conn.execute(
            "UPDATE paper_futures_accounts SET cash=? WHERE user_id=?", (cash, user_id)
        )


def get_paper_futures_position(user_id: int, product: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT product, side, qty, avg_price, open_fee_total FROM paper_futures_positions "
            "WHERE user_id=? AND product=?",
            (user_id, product)
        ).fetchone()
    return dict(row) if row else None


def upsert_paper_futures_position(user_id: int, product: str, side: str, qty: int, avg_price: float,
                                   open_fee_total: float = 0):
    with _conn() as conn:
        if qty <= 0:
            conn.execute(
                "DELETE FROM paper_futures_positions WHERE user_id=? AND product=?", (user_id, product)
            )
        else:
            conn.execute(
                "INSERT INTO paper_futures_positions(user_id, product, side, qty, avg_price, open_fee_total) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, product) DO UPDATE SET "
                "side=excluded.side, qty=excluded.qty, avg_price=excluded.avg_price, "
                "open_fee_total=excluded.open_fee_total",
                (user_id, product, side, qty, avg_price, open_fee_total)
            )


def get_paper_futures_positions(user_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT product, side, qty, avg_price FROM paper_futures_positions WHERE user_id=? ORDER BY product",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def insert_paper_futures_order(user_id: int, product: str, side: str, action: str, qty: int,
                                price: float, fee: float, tax: float, net_amount: float,
                                realized_pl: float | None, open_price: float | None = None):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO paper_futures_orders"
            "(user_id, product, side, action, qty, price, open_price, fee, tax, net_amount, realized_pl, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, product, side, action, qty, price, open_price, fee, tax, net_amount, realized_pl, time.time())
        )


def get_paper_futures_orders(user_id: int, limit: int = 50) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT product, side, action, qty, price, open_price, fee, tax, net_amount, realized_pl, created_at "
            "FROM paper_futures_orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_paper_futures_closed_trades(user_id: int) -> list[dict]:
    """取全部已平倉交易（action='close' 且有 realized_pl 的紀錄），依時間由舊到新，供績效分析用。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT product, side, qty, price, realized_pl, created_at FROM paper_futures_orders "
            "WHERE user_id=? AND action='close' AND realized_pl IS NOT NULL ORDER BY created_at ASC",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── price_alerts（個人化提醒：到價 / 掃描訊號）────────────

def create_price_alert(user_id: int, ticker: str, alert_type: str,
                        target_price: float | None = None, scan_type: str | None = None) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO price_alerts(user_id, ticker, alert_type, target_price, scan_type, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (user_id, ticker, alert_type, target_price, scan_type, time.time())
        )
        return cur.lastrowid


def get_alerts_for_user(user_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, ticker, alert_type, target_price, scan_type, active, triggered_at, created_at "
            "FROM price_alerts WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_price_alerts() -> list[dict]:
    """供 alert_price_check.py 用：全部啟用中的到價提醒（跨使用者）。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, user_id, ticker, alert_type, target_price FROM price_alerts "
            "WHERE active=1 AND alert_type IN ('price_above', 'price_below')"
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_scan_alerts(scan_type: str) -> list[dict]:
    """供 daily_update.py 用：某個掃描類型下全部啟用中的訊號提醒（跨使用者）。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, user_id, ticker FROM price_alerts "
            "WHERE active=1 AND alert_type='scan_signal' AND scan_type=?",
            (scan_type,)
        ).fetchall()
    return [dict(r) for r in rows]


def mark_alert_triggered(alert_id: int):
    with _conn() as conn:
        conn.execute(
            "UPDATE price_alerts SET active=0, triggered_at=? WHERE id=?",
            (time.time(), alert_id)
        )


def delete_alert(alert_id: int, user_id: int) -> bool:
    """刪除提醒，需驗證擁有者。回傳是否有刪除成功。"""
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM price_alerts WHERE id=? AND user_id=?",
            (alert_id, user_id)
        )
        return cur.rowcount > 0


def update_alert(alert_id: int, user_id: int, target_price: float | None = None,
                  scan_type: str | None = None) -> bool:
    """編輯提醒的目標價/訊號類型，並重新啟用（active=1, triggered_at=NULL），
    等同「改完繼續監控」。需驗證擁有者。回傳是否有更新成功。"""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE price_alerts SET "
            "target_price=COALESCE(?, target_price), "
            "scan_type=COALESCE(?, scan_type), "
            "active=1, triggered_at=NULL "
            "WHERE id=? AND user_id=?",
            (target_price, scan_type, alert_id, user_id)
        )
        return cur.rowcount > 0


# ── paper_futures_conditional_orders（期貨模擬下單智慧單：到價自動下單）──

def create_conditional_order(user_id: int, product: str, side: str, qty: int,
                              trigger_price: float, direction: str, order_type: str = "stop") -> int:
    """side 存 "buy"/"sell"（淨部位下單模式，開倉/平倉在觸發當下依實際持有部位判斷，
    不用使用者預先選，所以 action 欄位對新資料已不再使用，固定存空字串）。"""
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO paper_futures_conditional_orders"
            "(user_id, product, side, action, qty, trigger_price, direction, order_type, status, created_at) "
            "VALUES (?, ?, ?, '', ?, ?, ?, ?, 'pending', ?)",
            (user_id, product, side, qty, trigger_price, direction, order_type, time.time())
        )
        return cur.lastrowid


def get_conditional_orders(user_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, product, side, action, qty, trigger_price, direction, order_type, status, "
            "fail_reason, created_at, triggered_at, user_note FROM paper_futures_conditional_orders "
            "WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_conditional_order_note(user_id: int, order_id: int, note: str) -> bool:
    """更新使用者自行輸入的智慧單備註，需驗證擁有者。回傳是否有更新成功。"""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE paper_futures_conditional_orders SET user_note=? WHERE id=? AND user_id=?",
            (note, order_id, user_id)
        )
        return cur.rowcount > 0


def get_pending_conditional_orders() -> list[dict]:
    """供 futures_conditional_check.py 用：全部待觸發的智慧單（跨使用者）。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, user_id, product, side, action, qty, trigger_price, direction, order_type "
            "FROM paper_futures_conditional_orders WHERE status='pending'"
        ).fetchall()
    return [dict(r) for r in rows]


def mark_conditional_order_triggered(order_id: int):
    with _conn() as conn:
        conn.execute(
            "UPDATE paper_futures_conditional_orders SET status='triggered', triggered_at=? WHERE id=?",
            (time.time(), order_id)
        )


def mark_conditional_order_failed(order_id: int, reason: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE paper_futures_conditional_orders SET status='failed', fail_reason=?, triggered_at=? WHERE id=?",
            (reason, time.time(), order_id)
        )


def cancel_conditional_order(user_id: int, order_id: int) -> bool:
    """取消智慧單，需驗證擁有者、且必須還是 pending 狀態。回傳是否有取消成功。"""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE paper_futures_conditional_orders SET status='cancelled' "
            "WHERE id=? AND user_id=? AND status='pending'",
            (order_id, user_id)
        )
        return cur.rowcount > 0


# ── paper_conditional_orders（股票模擬下單智慧單：到價自動買賣）───

def create_stock_conditional_order(user_id: int, ticker: str, side: str, lots: int,
                                    trigger_price: float, direction: str, order_type: str = "stop") -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO paper_conditional_orders"
            "(user_id, ticker, side, lots, trigger_price, direction, order_type, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (user_id, ticker, side, lots, trigger_price, direction, order_type, time.time())
        )
        return cur.lastrowid


def get_stock_conditional_orders(user_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, ticker, side, lots, trigger_price, direction, order_type, status, "
            "fail_reason, created_at, triggered_at, user_note FROM paper_conditional_orders "
            "WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_stock_conditional_order_note(user_id: int, order_id: int, note: str) -> bool:
    """更新使用者自行輸入的智慧單備註，需驗證擁有者。回傳是否有更新成功。"""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE paper_conditional_orders SET user_note=? WHERE id=? AND user_id=?",
            (note, order_id, user_id)
        )
        return cur.rowcount > 0


def get_pending_stock_conditional_orders() -> list[dict]:
    """供 stock_conditional_check.py 用：全部待觸發的股票智慧單（跨使用者）。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, user_id, ticker, side, lots, trigger_price, direction, order_type "
            "FROM paper_conditional_orders WHERE status='pending'"
        ).fetchall()
    return [dict(r) for r in rows]


def mark_stock_conditional_order_triggered(order_id: int):
    with _conn() as conn:
        conn.execute(
            "UPDATE paper_conditional_orders SET status='triggered', triggered_at=? WHERE id=?",
            (time.time(), order_id)
        )


def mark_stock_conditional_order_failed(order_id: int, reason: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE paper_conditional_orders SET status='failed', fail_reason=?, triggered_at=? WHERE id=?",
            (reason, time.time(), order_id)
        )


def cancel_stock_conditional_order(user_id: int, order_id: int) -> bool:
    """取消智慧單，需驗證擁有者、且必須還是 pending 狀態。回傳是否有取消成功。"""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE paper_conditional_orders SET status='cancelled' "
            "WHERE id=? AND user_id=? AND status='pending'",
            (order_id, user_id)
        )
        return cur.rowcount > 0


def save_news_summary(date: str, summary: str, stock_watch: list | None = None):
    """存每日新聞重點摘要（AI整理）+ 台股觀察個股清單（直接從新聞關聯個股產生），一天一筆。"""
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO news_summaries(date, summary, stock_watch_json, created_at) VALUES (?, ?, ?, ?)",
            (date, summary, json.dumps(stock_watch or [], ensure_ascii=False), time.time())
        )


def get_latest_news_summary() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT date, summary, stock_watch_json, created_at FROM news_summaries ORDER BY date DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["stock_watch"] = json.loads(result.pop("stock_watch_json") or "[]")
    return result


