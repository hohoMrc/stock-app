from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app.services.revenue_data import (
    get_revenue_board,
    get_revenue_industry,
    get_revenue_months,
)

router = APIRouter(prefix="/api/revenue", tags=["revenue"])


@router.get("")
async def revenue_board(ym: str | None = Query(default=None)):
    """某月全部股票月營收（含官方已算好的成長率、近12月新高旗標）。
    榜單排序與規模/產業篩選由前端處理。"""
    try:
        return await run_in_threadpool(get_revenue_board, ym)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/meta")
async def revenue_meta():
    """可選月份清單與最新月份。"""
    try:
        months = await run_in_threadpool(get_revenue_months)
        return {"months": months, "latest": months[0] if months else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry")
async def revenue_industry(
    ym: str | None = Query(default=None),
    market: str | None = Query(default=None, description="L=上市 O=上櫃，省略為全部"),
):
    """產業成長榜。"""
    try:
        return await run_in_threadpool(get_revenue_industry, ym, market)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
