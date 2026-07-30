from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.services.stock_data import (
    get_taiex_quote, get_market_breadth, get_institutional_summary,
    get_industry_performance, get_movers_ranking,
    scan_ma_squeeze, scan_near_ema60, scan_volume_breakout, scan_institutional_buying,
)
from app.services.futures_data import get_futures_quote, get_institutional_positions

router = APIRouter(prefix="/api/market", tags=["market"])


def _build_overview() -> dict:
    """大盤狀態首頁彙總資料。各項來源獨立，平行抓取（多數已有各自的5分鐘快取），
    單一項目失敗不影響其他區塊，回傳 None 讓前端顯示「暫無資料」。
    """
    tasks = {
        "taiex":                get_taiex_quote,
        "breadth":              get_market_breadth,
        "institutional":        get_institutional_summary,
        "industry":             get_industry_performance,
        "movers_up":            lambda: get_movers_ranking("up", 5),
        "movers_down":          lambda: get_movers_ranking("down", 5),
        "ma_squeeze":           lambda: scan_ma_squeeze(500),
        "near_ema60":           lambda: scan_near_ema60(500),
        "volume_breakout":      lambda: scan_volume_breakout(500),
        "institutional_buying": lambda: scan_institutional_buying(3, 500, 0),
        "futures_quote":        get_futures_quote,
        "futures_positions":    get_institutional_positions,
    }
    results: dict = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        future_to_key = {pool.submit(fn): key for key, fn in tasks.items()}
        for fut in future_to_key:
            key = future_to_key[fut]
            try:
                results[key] = fut.result()
            except Exception as e:
                print(f"[market overview] {key} 失敗: {e}")
                results[key] = None

    industry = results.get("industry") or []
    positions = results.get("futures_positions") or []

    return {
        "taiex":         results.get("taiex"),
        "breadth":       results.get("breadth"),
        "institutional": results.get("institutional"),
        "futures": {
            "quote":            results.get("futures_quote"),
            "positions_latest": positions[-1] if positions else None,
        },
        "scan_counts": {
            "ma_squeeze":           len(results.get("ma_squeeze") or []),
            "near_ema60":           len(results.get("near_ema60") or []),
            "volume_breakout":      len(results.get("volume_breakout") or []),
            "institutional_buying": len(results.get("institutional_buying") or []),
        },
        "industry_top5":    industry[:5],
        "industry_bottom5": industry[-5:][::-1] if len(industry) > 5 else [],
        "movers_up_top5":   results.get("movers_up") or [],
        "movers_down_top5": results.get("movers_down") or [],
    }


@router.get("/overview")
async def market_overview():
    try:
        return await run_in_threadpool(_build_overview)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
