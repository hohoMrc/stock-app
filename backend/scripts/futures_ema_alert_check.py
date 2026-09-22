"""
微台指(TMF) 觸及 EMA 通知
執行時機：期貨日盤+夜盤交易時段每 2 分鐘，跟 futures_conditional_check.py 共用時段
用法：
  python3 scripts/futures_ema_alert_check.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import json
import time
import urllib.request
import urllib.parse

PRODUCT = "TMF"
COOLDOWN_SECONDS = 10 * 60  # 上下貫穿EMA很容易來回觸發，10分鐘內不重複通知


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


def _load_last_notified_ts(state_path: str) -> float:
    try:
        with open(state_path) as f:
            return json.load(f).get("last_notified_ts", 0)
    except Exception:
        return 0


def _save_last_notified_ts(state_path: str, ts: float):
    try:
        with open(state_path, "w") as f:
            json.dump({"last_notified_ts": ts}, f)
    except Exception as e:
        print(f"[微台EMA] 寫入狀態檔失敗（{state_path}）: {e}")


def check_ema_cross(*, timeframe: str, period: int, only_direction: str | None,
                     scan_type: str, state_filename: str, label: str):
    """檢查微台指在指定K棒週期下，是否剛穿越 EMA(period)。
    only_direction: None＝雙向都通知；"跌破"＝只在由上往下跌破時通知（不理會站上）。
    """
    from app.services.futures_data import get_futures_candles, _current_symbol
    from app.services.stock_data import ema_series
    from app.services.signal_tracking import record_signals

    symbol = _current_symbol(PRODUCT)
    candles = get_futures_candles(symbol, timeframe)
    closes = [c["close"] for c in candles if c.get("close") is not None]

    # EMA至少要餵3~4倍長度的資料才收斂準確（跟EMA60股票版同樣的道理，見 ema_series 說明）
    if len(closes) < period * 3:
        print(f"[{label}] {timeframe}分K資料不足（僅 {len(closes)} 根），略過")
        return

    emas = ema_series(closes, period)
    last_close, prev_close = closes[-1], closes[-2]
    last_ema, prev_ema = emas[-1], emas[-2]
    if last_ema is None or prev_ema is None:
        print(f"[{label}] EMA尚未算出，略過")
        return

    # 前一根跟這一根收盤價，剛好落在EMA的兩側（或正好貼線）→ 判定為穿越
    if (prev_close - prev_ema) * (last_close - last_ema) > 0:
        print(f"[{label}] 未觸發（價 {last_close}／EMA {round(last_ema, 1)}）")
        return

    direction = "站上" if last_close >= last_ema else "跌破"
    if only_direction and direction != only_direction:
        print(f"[{label}] 穿越方向是「{direction}」，不是要通知的「{only_direction}」，略過")
        return

    print(f"[{label}] {direction} EMA{period}（價 {last_close}／EMA {round(last_ema, 1)}）")
    record_signals(scan_type, [{"ticker": PRODUCT, "name": "微台指", "close": last_close}])

    state_path = os.path.join(os.path.dirname(__file__), state_filename)
    now_ts = time.time()
    elapsed = now_ts - _load_last_notified_ts(state_path)
    if elapsed >= COOLDOWN_SECONDS:
        _tg_notify(
            f"📍 微台指(TMF) {timeframe}分K {direction} EMA{period}\n"
            f"現價：{last_close}\nEMA{period}：{round(last_ema, 1)}"
        )
        _save_last_notified_ts(state_path, now_ts)
    else:
        print(f"[{label}] 冷卻中（距上次通知 {int(elapsed)} 秒），不重複發送")


print("[微台EMA] 開始檢查...")
try:
    from app.db import init_db
    init_db()

    check_ema_cross(
        timeframe="1", period=126, only_direction=None,
        scan_type="tmf_ema126_touch", state_filename=".futures_ema_alert_state.json",
        label="微台EMA126(1分K)",
    )
    check_ema_cross(
        timeframe="15", period=60, only_direction="跌破",
        scan_type="tmf_15m_below_ema60", state_filename=".futures_ema60_15m_alert_state.json",
        label="微台EMA60(15分K)",
    )

    try:
        from app.services.futures_data import shutdown_sdk
        shutdown_sdk()
    except Exception as e:
        print(f"[futures] shutdown_sdk 失敗: {e}")
except Exception as e:
    print(f"[微台EMA] 執行失敗: {e}")
