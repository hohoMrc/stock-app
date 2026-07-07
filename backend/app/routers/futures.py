from fastapi import APIRouter, Query, HTTPException
from app.services.futures_data import get_futures_quote, get_futures_candles, get_institutional_positions

router = APIRouter(prefix="/api/futures", tags=["futures"])

VALID_TIMEFRAMES = {"1", "5", "15", "30", "60", "D"}


@router.get("/quote")
async def futures_quote(symbol: str = Query(default=None)):
    try:
        return get_futures_quote(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candles")
async def futures_candles(
    symbol: str    = Query(default=None),
    timeframe: str = Query(default="60"),
):
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"timeframe 需為 {VALID_TIMEFRAMES}")
    try:
        return {"timeframe": timeframe, "data": get_futures_candles(symbol, timeframe)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/institutional")
async def institutional_positions():
    try:
        return {"data": get_institutional_positions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
