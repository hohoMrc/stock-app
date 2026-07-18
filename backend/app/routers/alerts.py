from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from app.routers.auth import verify_token
from app.services import alerts as svc

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _get_user(authorization: str | None) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="請先登入")
    return verify_token(authorization[7:])


class AlertBody(BaseModel):
    ticker: str
    alert_type: str
    target_price: float | None = None
    scan_type: str | None = None


@router.get("")
async def list_alerts(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return {"alerts": await run_in_threadpool(svc.list_alerts, user_id)}


@router.post("")
async def create_alert(body: AlertBody, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    try:
        alert_id = await run_in_threadpool(
            svc.add_alert, user_id, body.ticker, body.alert_type, body.target_price, body.scan_type
        )
        return {"id": alert_id}
    except svc.AlertError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{alert_id}")
async def remove_alert(alert_id: int, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    try:
        await run_in_threadpool(svc.remove_alert, user_id, alert_id)
        return {"ok": True}
    except svc.AlertError as e:
        raise HTTPException(status_code=400, detail=str(e))
