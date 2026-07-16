from fastapi import APIRouter, Query, HTTPException
from fastapi.concurrency import run_in_threadpool
from app.services.futures_data import get_futures_quote, get_futures_candles, get_institutional_positions, _current_symbol

router = APIRouter(prefix="/api/futures", tags=["futures"])

VALID_TIMEFRAMES = {"1", "5", "15", "30", "60", "D"}
VALID_PRODUCTS   = {"TXF", "TMF"}
VALID_SESSIONS   = {"regular", "afterhours"}


@router.get("/quote")
async def futures_quote(product: str = Query(default="TXF"), session: str = Query(default="regular")):
    if product not in VALID_PRODUCTS:
        raise HTTPException(status_code=400, detail="product 需為 TXF 或 TMF")
    if session not in VALID_SESSIONS:
        raise HTTPException(status_code=400, detail="session 需為 regular 或 afterhours")
    try:
        return await run_in_threadpool(get_futures_quote, _current_symbol(product), session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candles")
async def futures_candles(
    product:   str = Query(default="TXF"),
    timeframe: str = Query(default="60"),
    session:   str = Query(default="regular"),
):
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"timeframe 需為 {VALID_TIMEFRAMES}")
    if product not in VALID_PRODUCTS:
        raise HTTPException(status_code=400, detail="product 需為 TXF 或 TMF")
    if session not in VALID_SESSIONS:
        raise HTTPException(status_code=400, detail="session 需為 regular 或 afterhours")
    try:
        symbol = _current_symbol(product)
        data   = await run_in_threadpool(get_futures_candles, symbol, timeframe, session)
        return {"timeframe": timeframe, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/institutional")
async def institutional_positions():
    try:
        data = await run_in_threadpool(get_institutional_positions)
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
