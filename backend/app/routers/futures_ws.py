import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.futures_data import _current_symbol, add_ws_listener, remove_ws_listener

router = APIRouter()


@router.websocket("/ws/futures")
async def futures_ws(websocket: WebSocket, product: str = "TXF"):
    await websocket.accept()
    symbol = _current_symbol(product)
    loop   = asyncio.get_event_loop()
    queue  = asyncio.Queue()
    queue._loop = loop   # 讓 callback thread 可以拿到 loop

    # Fubon 訂閱失敗不關閉 WS；前端仍可透過 REST 輪詢取得資料
    try:
        await asyncio.to_thread(add_ws_listener, symbol, queue)
    except Exception as e:
        print(f"[WS] add_ws_listener 失敗（{symbol}）: {e}")
    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=25)
                await websocket.send_json(data)
            except asyncio.TimeoutError:
                # 無成交時送 keepalive，讓前端知道連線還活著
                try:
                    await websocket.send_json({"event": "keepalive"})
                except Exception:
                    break   # 送不出去代表前端已斷線
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        remove_ws_listener(symbol, queue)
