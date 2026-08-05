from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from app.routers.auth import verify_token
from app.services import paper_trading as svc

router = APIRouter(prefix="/api/paper", tags=["paper-trading"])


def _get_user(authorization: str | None) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="請先登入")
    return verify_token(authorization[7:])


class OrderBody(BaseModel):
    ticker: str
    side: str
    lots: int
    price: float | None = None


class SmartOrderBody(BaseModel):
    ticker: str
    side: str
    lots: int
    trigger_price: float
    order_type: str = "stop"


class SmartOrderNoteBody(BaseModel):
    note: str


@router.get("/account")
async def account(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return await run_in_threadpool(svc.get_account_summary, user_id)


@router.get("/positions")
async def positions(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return {"positions": await run_in_threadpool(svc.get_positions_with_price, user_id)}


@router.get("/orders")
async def orders(limit: int = Query(default=50, le=200), authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return {"orders": await run_in_threadpool(svc.get_order_history, user_id, limit)}


@router.get("/performance")
async def performance(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return await run_in_threadpool(svc.get_performance_stats, user_id)


@router.post("/order")
async def place_order(body: OrderBody, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    if body.side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="side 需為 buy 或 sell")
    if body.lots <= 0:
        raise HTTPException(status_code=400, detail="張數需大於 0")
    try:
        return await run_in_threadpool(svc.place_market_order, user_id, body.ticker, body.side, body.lots, body.price)
    except svc.PaperTradingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deposit")
async def deposit(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return await run_in_threadpool(svc.deposit_cash, user_id)


@router.post("/smart-order")
async def create_smart_order(body: SmartOrderBody, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    if body.side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="side 需為 buy 或 sell")
    if body.lots <= 0:
        raise HTTPException(status_code=400, detail="張數需大於 0")
    try:
        return await run_in_threadpool(
            svc.create_smart_order, user_id, body.ticker, body.side, body.lots,
            body.trigger_price, body.order_type
        )
    except svc.PaperTradingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/smart-orders")
async def smart_orders(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return {"orders": await run_in_threadpool(svc.get_smart_orders, user_id)}


@router.delete("/smart-orders/{order_id}")
async def delete_smart_order(order_id: int, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    ok = await run_in_threadpool(svc.cancel_smart_order, user_id, order_id)
    if not ok:
        raise HTTPException(status_code=400, detail="取消失敗（訂單不存在或已不是待觸發狀態）")
    return {"ok": True}


@router.patch("/smart-orders/{order_id}/note")
async def update_smart_order_note(order_id: int, body: SmartOrderNoteBody, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    ok = await run_in_threadpool(svc.update_smart_order_note, user_id, order_id, body.note)
    if not ok:
        raise HTTPException(status_code=400, detail="更新失敗（訂單不存在）")
    return {"ok": True}
