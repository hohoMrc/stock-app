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


@router.post("/order")
async def place_order(body: OrderBody, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    if body.side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="side 需為 buy 或 sell")
    if body.lots <= 0:
        raise HTTPException(status_code=400, detail="張數需大於 0")
    try:
        return await run_in_threadpool(svc.place_market_order, user_id, body.ticker, body.side, body.lots)
    except svc.PaperTradingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reset")
async def reset(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return await run_in_threadpool(svc.reset_account, user_id)
