"""
盤後每日 K 線更新腳本
執行時機：台灣時間 15:30（UTC 07:30）
用法：
  python3 scripts/daily_update.py          # 更新最近 7 天
  python3 scripts/daily_update.py --full   # 首次回填 3 個月（較慢，約 10 分鐘）
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import urllib.request, urllib.parse, json as _json

SITE_URL = "https://stock-app-lilac-nine.vercel.app"

def _tg_notify(text: str, html: bool = False):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        params = {"chat_id": chat_id, "text": text}
        if html:
            params["parse_mode"] = "HTML"
        payload = urllib.parse.urlencode(params).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", payload, timeout=10
        )
    except Exception as e:
        print(f"[TG] 通知失敗: {e}")

def _stock_link(ticker: str, name: str, extra: str = "") -> str:
    url = f"{SITE_URL}/?ticker={ticker}"
    return f'<a href="{url}">{ticker} {name}</a>{extra}'

from app.db import init_db, save_candles, bulk_save_stock_meta, _conn
from app.services.stock_data import (
    _fugle_candles, _load_tw_stock_names,
    _tw_stock_names, _tw_stock_industry, _tw_stock_exchange,
    TICKER_INDUSTRY_OVERRIDE,
)
from datetime import date, timedelta
import time

init_db()
_load_tw_stock_names()

# 批次寫入所有股票的 meta（名稱、細分產業、大分類、交易所）
# industry = TICKER_INDUSTRY_OVERRIDE 細分類（優先），否則用 TWSE 大分類
# parent_industry = 永遠是 TWSE 大分類（供退路查詢用）
_meta_records = [
    (
        t,
        _tw_stock_names.get(t),
        TICKER_INDUSTRY_OVERRIDE.get(t) or _tw_stock_industry.get(t),
        _tw_stock_industry.get(t),   # parent_industry
        _tw_stock_exchange.get(t, "TW"),
    )
    for t in _tw_stock_names
]
bulk_save_stock_meta(_meta_records)
print(f"[daily_update] 已更新 {len(_meta_records)} 筆股票 meta")

FULL_MODE = "--full" in sys.argv


def get_all_tickers() -> list[str]:
    """回傳所有要更新的代號：TWSE 完整清單 + 上櫃常見股。"""
    tickers = list(_tw_stock_names.keys())
    # 補上不在 TWSE 清單的 ETF / 上櫃股
    extras = ["0056", "00878", "006208", "00881", "00713", "00900", "4904", "3045"]
    for t in extras:
        if t not in tickers:
            tickers.append(t)
    return tickers


def update_ticker(ticker: str, days: int = 7, retries: int = 3) -> int:
    today   = date.today()
    from_dt = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    to_dt   = today.strftime("%Y-%m-%d")
    for attempt in range(retries):
        try:
            records = _fugle_candles(ticker, from_dt, to_dt)
            if records:
                save_candles(ticker, records)
                return len(records)
            return 0
        except Exception as e:
            if "429" in str(e) or "Rate limit" in str(e):
                wait = 30 * (attempt + 1)
                print(f"  [rate limit] {ticker}，等待 {wait}s...")
                time.sleep(wait)
            else:
                raise
    return 0


if __name__ == "__main__":
    tickers = get_all_tickers()
    days    = 90 if FULL_MODE else 7
    mode    = "回填 3 個月" if FULL_MODE else "更新 7 天"
    delay   = 1.0 if FULL_MODE else 0.5   # full 模式放慢避免 rate limit

    print(f"[daily_update] {mode}，共 {len(tickers)} 支股票（間隔 {delay}s）...")
    ok = fail = skip = 0

    for i, t in enumerate(tickers, 1):
        try:
            n = update_ticker(t, days)
            if n:
                ok += 1
            else:
                skip += 1
        except Exception as e:
            print(f"  ✗ {t}: {e}")
            fail += 1
        if i % 100 == 0:
            print(f"  進度 {i}/{len(tickers)}，成功 {ok}，無資料 {skip}，失敗 {fail}")
        time.sleep(delay)

    msg = f"[股票更新] {'全量回填' if FULL_MODE else '每日更新'} 完成\n✅ 成功 {ok} 支 / ⏭ 無資料 {skip} / ❌ 失敗 {fail}"
    print(msg)
    _tg_notify(msg)

    # 全量模式不跑 MA 黏合（資料剛回填，不具參考性）
    if not FULL_MODE:
        print("[MA黏合] 開始掃描...")
        try:
            from app.services.stock_data import scan_ma_squeeze
            hits = scan_ma_squeeze(500)
            if hits:
                lines = [
                    _stock_link(s["ticker"], s.get("name", ""), f"  {s.get('close') or s.get('price', '')}元")
                    for s in hits
                ]
                squeeze_msg = f"[MA黏合] 今日找到 {len(hits)} 支\n" + "\n".join(lines)
            else:
                squeeze_msg = "[MA黏合] 今日無符合條件的股票"
            print(squeeze_msg)
            _tg_notify(squeeze_msg, html=True)
        except Exception as e:
            print(f"[MA黏合] 掃描失敗: {e}")

    # 儲存台指期當日各 timeframe 盤中 K 棒到 DB
    print("[期貨K線] 儲存當日各 timeframe K 棒...")
    try:
        from app.services.futures_data import _current_symbol, _get_client, TZ_TAIPEI
        from app.db import save_futures_candles
        import datetime as _dt
        symbol  = _current_symbol("TXF")
        product = "TXF"
        for tf in ["1", "5", "15", "30", "60"]:
            try:
                data    = _get_client().futopt.intraday.candles(symbol=symbol, timeframe=tf)
                candles = []
                for c in data.get("data", []):
                    raw_dt = _dt.datetime.fromisoformat(c["date"])
                    if raw_dt.tzinfo is None:
                        raw_dt = raw_dt.replace(tzinfo=TZ_TAIPEI)
                    candles.append({
                        "time":   int(raw_dt.timestamp()),
                        "open":   c["open"],
                        "high":   c["high"],
                        "low":    c["low"],
                        "close":  c["close"],
                        "volume": c.get("volume", 0),
                    })
                if candles:
                    save_futures_candles(product, tf, candles)
                    print(f"[期貨K線] TXF {tf}min: 存入 {len(candles)} 根")
            except Exception as e:
                print(f"[期貨K線] TXF {tf}min 失敗: {e}")
    except Exception as e:
        print(f"[期貨K線] 整體失敗: {e}")
