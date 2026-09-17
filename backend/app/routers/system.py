from fastapi import APIRouter, Depends

from app.db import get_system_status
from app.routers.admin import _require_admin

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
def status(_: int = Depends(_require_admin)):
    return get_system_status()
