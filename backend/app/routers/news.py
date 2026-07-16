from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from app.services.news_data import get_hot_news

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/hot")
async def hot_news(limit: int = Query(default=20, le=50)):
    try:
        news = await run_in_threadpool(get_hot_news, limit)
        return {"count": len(news), "news": news}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
