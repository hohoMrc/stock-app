from fastapi import APIRouter, Query, HTTPException
from app.services.futures_data import get_futures_quote, get_futures_candles, get_institutional_positions, _current_symbol

router = APIRouter(prefix="/api/futures", tags=["futures"])

VALID_TIMEFRAMES = {"1", "5", "15", "30", "60", "D"}
VALID_PRODUCTS   = {"TXF", "TMF"}


@router.get("/quote")
async def futures_quote(product: str = Query(default="TXF")):
    if product not in VALID_PRODUCTS:
        raise HTTPException(status_code=400, detail="product 需為 TXF 或 TMF")
    try:
        return get_futures_quote(_current_symbol(product))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candles")
async def futures_candles(
    product:   str = Query(default="TXF"),
    timeframe: str = Query(default="60"),
):
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"timeframe 需為 {VALID_TIMEFRAMES}")
    if product not in VALID_PRODUCTS:
        raise HTTPException(status_code=400, detail="product 需為 TXF 或 TMF")
    try:
        symbol = _current_symbol(product)
        return {"timeframe": timeframe, "data": get_futures_candles(symbol, timeframe)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/institutional")
async def institutional_positions():
    try:
        return {"data": get_institutional_positions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
