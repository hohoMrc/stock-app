from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from app.services.news_data import get_hot_news
from app.db import get_latest_news_summary

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/hot")
async def hot_news(limit: int = Query(default=20, le=100)):
    try:
        news = await run_in_threadpool(get_hot_news, limit)
        return {"count": len(news), "news": news}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def news_summary():
    try:
        result = await run_in_threadpool(get_latest_news_summary)
        return result or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
