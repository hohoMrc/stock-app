from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from app.services.signal_tracking import get_signal_overview

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/overview")
async def overview(days: int = Query(default=180, le=365)):
    try:
        return {"data": await run_in_threadpool(get_signal_overview, days)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
