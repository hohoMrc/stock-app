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

def _tg_chat_ids() -> list:
    """通知目標：個人 + 群組（TELEGRAM_GROUP_CHAT_ID 未設定時只發個人）。"""
    ids = []
    personal = os.environ.get("TELEGRAM_CHAT_ID")
    group    = os.environ.get("TELEGRAM_GROUP_CHAT_ID")
    if personal:
        ids.append(personal)
    if group:
        ids.append(group)
    return ids

def _tg_notify(text: str, html: bool = False):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    for chat_id in _tg_chat_ids():
        try:
            params = {"chat_id": chat_id, "text": text}
            if html:
                params["parse_mode"] = "HTML"
            payload = urllib.parse.urlencode(params).encode()
            urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/sendMessage", payload, timeout=10
            )
        except Exception as e:
            print(f"[TG] 通知失敗 (chat_id={chat_id}): {e}")

def _stock_link(ticker: str, name: str, extra: str = "", scan: str = "") -> str:
    url = f"{SITE_URL}/?ticker={ticker}"
    if scan:
        url += f"&scan={scan}"
    return f'<a href="{url}">{ticker} {name}</a>{extra}'

TG_MAX_LEN = 3900  # Telegram 單則訊息上限 4096 字元，留點安全邊界

def _tg_notify_lines(title: str, lines: list[str], empty_text: str):
    """依 Telegram 4096 字元上限自動分段發送，避免股票數太多導致單則訊息過長被拒（HTTP 400）。"""
    if not lines:
        print(empty_text)
        _tg_notify(empty_text, html=True)
        return

    chunks, cur, cur_len = [], [], 0
    for line in lines:
        if cur and cur_len + len(line) + 1 > TG_MAX_LEN:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        chunks.append(cur)

    for i, chunk in enumerate(chunks):
        header = title if i == 0 else f"{title}（續 {i + 1}/{len(chunks)}）"
        msg = header + "\n" + "\n".join(chunk)
        print(msg)
        _tg_notify(msg, html=True)

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
    delay   = 1.5 if FULL_MODE else 1.5   # 至少 1.5s 避免 Fugle rate limit (100 req/min)

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
        print("[鳥嘴與分歧] 開始掃描（日K 5MA/20MA）...")
        try:
            from app.services.stock_data import scan_ma_squeeze
            hits = scan_ma_squeeze(500)
            lines = [
                _stock_link(s["ticker"], s.get("name", ""), scan="bird_beak")
                for s in hits
            ]
            _tg_notify_lines(
                f"[鳥嘴與分歧] 日K 5MA/20MA，今日找到 {len(hits)} 支",
                lines,
                "[鳥嘴與分歧] 日K 5MA/20MA，今日無符合條件的股票",
            )
        except Exception as e:
            print(f"[鳥嘴與分歧] 掃描失敗: {e}")

        print("[EMA60近線] 開始掃描...")
        try:
            from app.services.stock_data import scan_near_ema60
            ema_hits = scan_near_ema60(500)
            lines = [
                _stock_link(s["ticker"], s.get("name", ""), scan="near_ema60")
                for s in ema_hits
            ]
            _tg_notify_lines(
                f"[EMA60近線] 今日找到 {len(ema_hits)} 支",
                lines,
                "[EMA60近線] 今日無符合條件的股票",
            )
        except Exception as e:
            print(f"[EMA60近線] 掃描失敗: {e}")

        print("[量價突破] 開始掃描...")
        try:
            from app.services.stock_data import scan_volume_breakout
            vb_hits = scan_volume_breakout(200)
            lines = [
                _stock_link(s["ticker"], s.get("name", ""))
                for s in vb_hits
            ]
            _tg_notify_lines(
                f"[量價突破] 爆量創20日新高，今日找到 {len(vb_hits)} 支",
                lines,
                "[量價突破] 今日無符合條件的股票",
            )
        except Exception as e:
            print(f"[量價突破] 掃描失敗: {e}")

        print("[三大法人] 抓取今日買賣超資料...")
        try:
            from app.services.stock_data import fetch_institutional_trades_today, scan_institutional_buying
            from app.db import save_institutional_trades
            inst_records = fetch_institutional_trades_today()
            save_institutional_trades(inst_records)
            print(f"[三大法人] 存入 {len(inst_records)} 筆")

            print("[法人連買] 開始掃描...")
            buy_hits = scan_institutional_buying(min_days=3, limit=200, min_total_net_zhang=5000)
            lines = [
                _stock_link(s["ticker"], s.get("name", ""), f"  {s['close']}元 連{s['streak_days']}天 合計{s['total_net_zhang']}張")
                for s in buy_hits
            ]
            _tg_notify_lines(
                f"[法人連買] 外資+投信連續買超≥3天且合計≥5000張，今日找到 {len(buy_hits)} 支",
                lines,
                "[法人連買] 今日無符合條件的股票（連續買超≥3天且合計≥5000張）",
            )
        except Exception as e:
            print(f"[三大法人/法人連買] 失敗: {e}")

    # 儲存台指期/微型台指當日各 timeframe 日盤 K 棒到 DB（夜盤由另一支排程 night_update.py 在隔天 05:30 存）
    print("[期貨K線] 儲存當日各 timeframe K 棒...")
    try:
        from app.services.futures_data import _current_symbol, _get_client, TZ_TAIPEI
        from app.db import save_futures_candles
        import datetime as _dt
        for product in ["TXF", "TMF"]:
            symbol = _current_symbol(product)
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
                        print(f"[期貨K線] {product} {tf}min: 存入 {len(candles)} 根")
                except Exception as e:
                    print(f"[期貨K線] {product} {tf}min 失敗: {e}")
    except Exception as e:
        print(f"[期貨K線] 整體失敗: {e}")
