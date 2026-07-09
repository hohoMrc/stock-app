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
    """回傳所有有 K 線的 ticker 及其 name、exchange。"""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT c.ticker, m.name, m.exchange
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
            "SELECT ticker, note FROM watchlists WHERE user_id=? ORDER BY added_at DESC",
            (user_id,)
        ).fetchall()
    return [{"ticker": r["ticker"], "note": r["note"] or ""} for r in rows]


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
