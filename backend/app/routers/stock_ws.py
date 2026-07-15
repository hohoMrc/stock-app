import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.stock_data import add_ws_listener, remove_ws_listener

router = APIRouter()


@router.websocket("/ws/stock")
async def stock_ws(websocket: WebSocket, symbol: str):
    await websocket.accept()
    loop  = asyncio.get_event_loop()
    queue = asyncio.Queue()
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
                # 無資料時送 keepalive，讓前端知道連線還活著
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


@router.websocket("/ws/stocks")
async def stocks_ws(websocket: WebSocket, symbols: str):
    """多檔股票即時推播（左側排行清單用），symbols 為逗號分隔的代號字串。"""
    await websocket.accept()
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()][:100]   # 安全上限
    loop  = asyncio.get_event_loop()
    queue = asyncio.Queue()
    queue._loop = loop

    added = []
    for sym in symbol_list:
        try:
            await asyncio.to_thread(add_ws_listener, sym, queue)
            added.append(sym)
        except Exception as e:
            print(f"[WS] add_ws_listener 失敗（{sym}）: {e}")
    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=25)
                await websocket.send_json(data)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"event": "keepalive"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        for sym in added:
            remove_ws_listener(sym, queue)
