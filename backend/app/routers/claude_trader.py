from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from app.services.claude_trader import get_claude_portfolio, get_claude_strategy_summary, get_claude_performance

router = APIRouter(prefix="/api/claude-trader", tags=["claude-trader"])

VALID_STRATEGIES = {"longterm", "shortterm"}


@router.get("/portfolio/{strategy}")
async def portfolio(strategy: str):
    if strategy not in VALID_STRATEGIES:
        raise HTTPException(status_code=400, detail="strategy 需為 longterm 或 shortterm")
    try:
        return await run_in_threadpool(get_claude_portfolio, strategy)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/{strategy}")
async def performance(strategy: str):
    if strategy not in VALID_STRATEGIES:
        raise HTTPException(status_code=400, detail="strategy 需為 longterm 或 shortterm")
    try:
        return await run_in_threadpool(get_claude_performance, strategy)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def config():
    try:
        return await run_in_threadpool(get_claude_strategy_summary)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
