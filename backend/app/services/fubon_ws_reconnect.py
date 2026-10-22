"""富邦行情 WebSocket 的連線與斷線自動重連（股票 stock_data、期貨 futures_data 共用）。"""
import threading
import time

from fugle_marketdata.websocket.client import AuthenticationState

_running: set[str] = set()   # 正在背景重連的連線名稱，避免 disconnect/error/close 同時觸發開多條
_running_lock = threading.Lock()


def connect_client(client, timeout: float = 10) -> None:
    """(重新)連線並等待登入完成。

    SDK 的 connect() 是無逾時的忙等迴圈，且被動斷線後 auth_status 不會重置，
    再呼叫 connect() 會沒連上就直接 return。所以先 disconnect() 重置狀態，
    再放到子執行緒連線，超過 timeout 就強制中止。
    """
    raw = getattr(client, "_client", client)   # 拆掉富邦的 wrapper，拿到真正的 WebSocketClient
    was_used = raw.auth_status != AuthenticationState.PENDING
    raw.disconnect()
    if was_used:
        time.sleep(1)   # 讓舊連線的 close 事件先跑完，免得誤判成新連線斷線

    err: list[Exception] = []

    def _run():
        try:
            raw.connect()
        except Exception as e:
            err.append(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        # 讓 SDK 的忙等迴圈結束
        raw.error = TimeoutError(f"富邦 WS 連線逾時（{timeout} 秒）")
        raw.auth_status = AuthenticationState.UNAUTHENTICATED
        t.join(3)
        raw.disconnect()
        raise TimeoutError(f"富邦 WS 連線逾時（{timeout} 秒）")
    if err:
        raise err[0]


def start_reconnect(name: str, reconnect_fn) -> None:
    """背景重連：3 秒後開始，失敗就加倍等待（上限 60 秒），直到 reconnect_fn 不再丟錯。"""
    with _running_lock:
        if name in _running:
            return
        _running.add(name)

    def _loop():
        delay = 3
        try:
            while True:
                time.sleep(delay)
                try:
                    reconnect_fn()
                    print(f"[Fubon WS] {name} 自動重連完成")
                    return
                except Exception as e:
                    print(f"[Fubon WS] {name} 自動重連失敗，{min(delay * 2, 60)} 秒後再試: {e}")
                    delay = min(delay * 2, 60)
        finally:
            with _running_lock:
                _running.discard(name)

    threading.Thread(target=_loop, daemon=True, name=f"ws-reconnect-{name}").start()
