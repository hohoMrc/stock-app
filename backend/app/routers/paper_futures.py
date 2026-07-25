from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from app.routers.auth import verify_token
from app.services import paper_futures as svc

router = APIRouter(prefix="/api/paper-futures", tags=["paper-futures"])


def _get_user(authorization: str | None) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="請先登入")
    return verify_token(authorization[7:])


class FuturesOrderBody(BaseModel):
    product: str
    side: str
    action: str
    qty: int
    price: float | None = None


@router.get("/account")
async def account(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return await run_in_threadpool(svc.get_futures_account_summary, user_id)


@router.get("/positions")
async def positions(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return {"positions": await run_in_threadpool(svc.get_futures_positions_with_price, user_id)}


@router.get("/orders")
async def orders(limit: int = Query(default=50, le=200), authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return {"orders": await run_in_threadpool(svc.get_futures_order_history, user_id, limit)}


@router.get("/performance")
async def performance(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return await run_in_threadpool(svc.get_futures_performance_stats, user_id)


@router.post("/order")
async def place_order(body: FuturesOrderBody, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    if body.product not in ("TXF", "TMF"):
        raise HTTPException(status_code=400, detail="product 需為 TXF 或 TMF")
    if body.side not in ("long", "short"):
        raise HTTPException(status_code=400, detail="side 需為 long 或 short")
    if body.action not in ("open", "close"):
        raise HTTPException(status_code=400, detail="action 需為 open 或 close")
    if body.qty <= 0:
        raise HTTPException(status_code=400, detail="口數需大於 0")
    try:
        return await run_in_threadpool(
            svc.place_futures_order, user_id, body.product, body.side, body.action, body.qty, body.price
        )
    except svc.PaperFuturesError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deposit")
async def deposit(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return await run_in_threadpool(svc.deposit_futures_cash, user_id)
