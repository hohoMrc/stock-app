from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

router = APIRouter(prefix="/api/warrants", tags=["warrants"])


@router.get("/lookup")
async def lookup_warrant(q: str = Query(...)):
    """單一入口查詢：輸入可以是股票代號（回傳該股所有相關權證）或權證代號本身（回傳單檔詳細資料）。"""
    query = q.strip().upper()
    if not query:
        raise HTTPException(status_code=400, detail="請輸入股票或權證代號")

    try:
        from app.db import get_warrants_by_underlying, get_warrant_by_ticker
        from app.services.warrant_data import get_stock_warrants, get_warrant_detail

        if await run_in_threadpool(get_warrants_by_underlying, query, 1):
            result = await run_in_threadpool(get_stock_warrants, query)
            return {
                "mode": "stock",
                "underlying_ticker": query,
                "count": len(result["warrants"]),
                "hist_vol_pct": result["hist_vol_pct"],
                "warrants": result["warrants"],
            }

        if await run_in_threadpool(get_warrant_by_ticker, query):
            warrant = await run_in_threadpool(get_warrant_detail, query)
            if warrant:
                return {"mode": "warrant", "warrant": warrant}

        return {"mode": "not_found"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
