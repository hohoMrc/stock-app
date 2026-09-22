"""
微台指(TMF) 觸及 EMA126 通知（用1分K算）
執行時機：期貨日盤+夜盤交易時段每 2 分鐘，跟 futures_conditional_check.py 共用時段
用法：
  python3 scripts/futures_ema_alert_check.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import urllib.request
import urllib.parse

PRODUCT = "TMF"
EMA_PERIOD = 126


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
        print("[TG] 未設定 TELEGRAM_BOT_TOKEN")
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


print("[微台EMA126] 開始檢查...")
try:
    from app.db import init_db
    from app.services.futures_data import get_futures_candles, _current_symbol, shutdown_sdk
    from app.services.stock_data import ema_series
    from app.services.signal_tracking import record_signals

    init_db()

    symbol = _current_symbol(PRODUCT)
    candles = get_futures_candles(symbol, "1")
    closes = [c["close"] for c in candles if c.get("close") is not None]

    # EMA126 至少要餵3~4倍長度的資料才收斂準確（跟EMA60同樣的道理，見 ema_series 說明）
    if len(closes) < EMA_PERIOD * 3:
        print(f"[微台EMA126] 1分K資料不足（僅 {len(closes)} 根），略過")
    else:
        emas = ema_series(closes, EMA_PERIOD)
        last_close, prev_close = closes[-1], closes[-2]
        last_ema, prev_ema = emas[-1], emas[-2]

        if last_ema is None or prev_ema is None:
            print("[微台EMA126] EMA尚未算出，略過")
        elif (prev_close - prev_ema) * (last_close - last_ema) <= 0:
            # 前一根跟這一根收盤價，剛好落在EMA126的兩側（或正好貼線）→ 判定為觸價
            direction = "站上" if last_close >= last_ema else "跌破"
            print(f"[微台EMA126] 觸價：{direction} EMA126（價 {last_close}／EMA {round(last_ema, 1)}）")
            record_signals("tmf_ema126_touch", [{"ticker": PRODUCT, "name": "微台指", "close": last_close}])
            _tg_notify(
                f"📍 微台指(TMF) 價格{direction} EMA126\n"
                f"現價：{last_close}\nEMA126：{round(last_ema, 1)}"
            )
        else:
            print(f"[微台EMA126] 未觸價（價 {last_close}／EMA {round(last_ema, 1)}）")

    try:
        shutdown_sdk()
    except Exception as e:
        print(f"[futures] shutdown_sdk 失敗: {e}")
except Exception as e:
    print(f"[微台EMA126] 執行失敗: {e}")
