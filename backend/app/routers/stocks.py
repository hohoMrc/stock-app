from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from app.services.stock_data import get_stock_info, get_stock_history, screen_stocks, get_stocks_by_industry, scan_all_weekly_surge, scan_ma_squeeze, scan_near_ema60, scan_volume_breakout, scan_institutional_buying, search_stocks, get_trade_value_ranking, get_turnover_ranking, get_movers_ranking, get_stock_orderbook, get_stock_trades, get_watchlist_quotes, get_institutional_trades_history
from app.services.ai_analysis import analyze_stock

router = APIRouter(prefix="/api/stocks", tags=["stocks"])

DEFAULT_TICKERS = [
    "2330", "2317", "2454", "2412", "2308",
    "2303", "1301", "1303", "2882", "2881",
    "2891", "2886", "3711", "2357", "2379",
]


class ScreenFilter(BaseModel):
    tickers: list = DEFAULT_TICKERS
    # 基本條件（快速，不需額外 API）
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_volume: Optional[float] = None        # 張
    min_market_cap: Optional[float] = None    # 億元
    max_market_cap: Optional[float] = None
    min_capital: Optional[float] = None       # 股本億元
    min_pe: Optional[float] = None
    max_pe: Optional[float] = None
    min_dividend_yield: Optional[float] = None
    # 週漲幅（需 10d 歷史）
    min_weekly_change: Optional[float] = None  # %
    # 線型條件（需額外 API）
    near_ma: Optional[str] = None
    near_ma_pct: float = 3.0
    pattern: Optional[str] = None
    # 技術面條件
    min_prev_day_change: Optional[float] = None  # 前日漲幅 ≥ %
    ma20_rising: bool = False                    # MA20 向上
    price_above_ma5_ma60: bool = False           # 收盤 > MA5 且 MA60


@router.get("/search")
async def search(q: str = Query(..., min_length=1)):
    results = search_stocks(q, limit=10)
    return {"results": results}


@router.get("/scan/weekly-surge")
async def weekly_surge_scan(
    min_weekly_change: float = Query(default=20.0),
    min_volume: float = Query(default=1000.0),
    min_capital: float = Query(default=2.0),
):
    try:
        results = scan_all_weekly_surge(min_weekly_change, min_volume, min_capital)
        return {"count": len(results), "stocks": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scan/ma-squeeze")
async def ma_squeeze_scan(limit: int = Query(default=200, le=500)):
    try:
        results = scan_ma_squeeze(limit)
        return {"count": len(results), "stocks": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scan/near-ema60")
async def near_ema60_scan(limit: int = Query(default=500, le=500)):
    try:
        results = await run_in_threadpool(scan_near_ema60, limit)
        return {"count": len(results), "stocks": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scan/volume-breakout")
async def volume_breakout_scan(limit: int = Query(default=200, le=500)):
    try:
        results = await run_in_threadpool(scan_volume_breakout, limit)
        return {"count": len(results), "stocks": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scan/institutional-buying")
async def institutional_buying_scan(
    min_days: int = Query(default=3, ge=1, le=20),
    limit: int = Query(default=200, le=500),
    min_total_net_zhang: int = Query(default=0, ge=0),
):
    try:
        results = await run_in_threadpool(scan_institutional_buying, min_days, limit, min_total_net_zhang)
        return {"count": len(results), "stocks": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ranking/trade-value")
async def trade_value_ranking(limit: int = Query(default=50, le=100), force: bool = Query(default=False)):
    try:
        stocks = get_trade_value_ranking(limit, force=force)
        return {"count": len(stocks), "stocks": stocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ranking/turnover")
async def turnover_ranking(limit: int = Query(default=50, le=100), force: bool = Query(default=False)):
    try:
        stocks = get_turnover_ranking(limit, force=force)
        return {"count": len(stocks), "stocks": stocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ranking/movers")
async def movers_ranking(
    direction: str = Query(default="up"),
    limit: int = Query(default=50, le=100),
    force: bool = Query(default=False),
):
    if direction not in ("up", "down"):
        raise HTTPException(status_code=400, detail="direction 需為 up 或 down")
    try:
        stocks = get_movers_ranking(direction, limit, force=force)
        return {"count": len(stocks), "stocks": stocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/watchlist-quotes")
async def watchlist_quotes(tickers: str = Query(..., min_length=1)):
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()][:100]
    try:
        stocks = await run_in_threadpool(get_watchlist_quotes, ticker_list)
        return {"count": len(stocks), "stocks": stocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/screen")
async def screen(filters: ScreenFilter):
    try:
        results = await run_in_threadpool(screen_stocks, filters.tickers, filters.model_dump(exclude={"tickers"}))
        return {"count": len(results), "stocks": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry/{industry}")
async def get_by_industry(industry: str, exclude: str = ""):
    try:
        stocks = get_stocks_by_industry(industry, exclude_ticker=exclude or None)
        return {"industry": industry, "count": len(stocks), "stocks": stocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/orderbook")
async def get_orderbook(ticker: str):
    try:
        return get_stock_orderbook(ticker)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/institutional-trades")
async def get_institutional_trades(ticker: str, days: int = Query(default=30, le=90)):
    try:
        records = await run_in_threadpool(get_institutional_trades_history, ticker, days)
        return {"ticker": ticker, "count": len(records), "records": records}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/trades")
async def get_trades(ticker: str, limit: int = Query(default=30, le=100)):
    try:
        return {"ticker": ticker, "trades": get_stock_trades(ticker, limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/history")
async def get_history(
    ticker: str,
    period: str = Query(default="3mo", pattern="^(1d|3d|5d|1mo|3mo|6mo|1y|2y|5y)$"),
    interval: str = Query(default="1d", pattern="^(1m|5m|15m|60m|1d|1wk|1mo)$"),
):
    try:
        history = get_stock_history(ticker, period, interval)
        return {"ticker": ticker, "period": period, "interval": interval, "data": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/analyze")
async def analyze(ticker: str):
    try:
        info = get_stock_info(ticker)
        if not info.get("price"):
            raise HTTPException(status_code=404, detail=f"找不到股票 {ticker}")
        history = get_stock_history(ticker, "3mo")
        analysis = analyze_stock(info, history)
        return {"ticker": ticker, "analysis": analysis}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}")
async def get_stock(ticker: str):
    try:
        info = get_stock_info(ticker)
        if not info.get("price"):
            raise HTTPException(status_code=404, detail=f"找不到股票 {ticker}")
        return info
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
