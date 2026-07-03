from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from app.db import get_all_users, get_user_by_id, update_user_password, delete_user
from app.routers.auth import verify_token, _hash_password

ADMIN_USERNAME = "hoholin"
router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(authorization: str = Header(...)) -> int:
    token = authorization.replace("Bearer ", "")
    user_id = verify_token(token)
    user = get_user_by_id(user_id)
    if not user or user["username"] != ADMIN_USERNAME:
        raise HTTPException(status_code=403, detail="權限不足")
    return user_id


@router.get("/users")
def list_users(_: int = Depends(_require_admin)):
    return {"users": get_all_users()}


class ChangePasswordBody(BaseModel):
    new_password: str


@router.patch("/users/{target_id}/password")
def change_password(target_id: int, body: ChangePasswordBody, _: int = Depends(_require_admin)):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="密碼至少 6 個字元")
    update_user_password(target_id, _hash_password(body.new_password))
    return {"ok": True}


@router.delete("/users/{target_id}")
def remove_user(target_id: int, admin_id: int = Depends(_require_admin)):
    if target_id == admin_id:
        raise HTTPException(status_code=400, detail="不能刪除自己")
    delete_user(target_id)
    return {"ok": True}
