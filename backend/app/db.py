import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent.parent / "stock_cache.db"


def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as conn:
        conn.executescript("""
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
        """)
        # Migration: 舊版 DB 沒有 parent_industry 欄位
        try:
            conn.execute("ALTER TABLE stock_meta ADD COLUMN parent_industry TEXT")
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
            "INSERT OR REPLACE INTO stock_meta"
            "(ticker, name, industry, parent_industry, exchange, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
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
