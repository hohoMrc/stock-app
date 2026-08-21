from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from app.routers.auth import verify_token
from app.db import (
    get_watchlist, add_to_watchlist, remove_from_watchlist, update_watchlist_note,
    get_watchlist_groups, rename_watchlist_group, update_watchlist_group,
    WATCHLIST_GROUP_COUNT,
)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _get_user(authorization: str | None) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="請先登入")
    return verify_token(authorization[7:])


def _check_group_id(group_id: int):
    if not (1 <= group_id <= WATCHLIST_GROUP_COUNT):
        raise HTTPException(status_code=400, detail=f"group_id 需為 1~{WATCHLIST_GROUP_COUNT}")


@router.get("")
def list_watchlist(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    items = get_watchlist(user_id)
    return {
        "tickers": [i["ticker"] for i in items],
        "notes": {i["ticker"]: i["note"] for i in items},
        "added_at": {i["ticker"]: i["added_at"] for i in items},
        "groups_by_ticker": {i["ticker"]: i["group_id"] for i in items},
    }


@router.get("/groups")
def list_groups(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    return {"groups": get_watchlist_groups(user_id)}


class GroupNameBody(BaseModel):
    name: str


@router.patch("/groups/{group_id}")
def rename_group(group_id: int, body: GroupNameBody, authorization: str | None = Header(None)):
    _check_group_id(group_id)
    user_id = _get_user(authorization)
    name = body.name.strip()[:20] or f"分組{group_id}"
    rename_watchlist_group(user_id, group_id, name)
    return {"ok": True}


@router.post("/{ticker}")
def add_watch(ticker: str, group_id: int = 1, authorization: str | None = Header(None)):
    _check_group_id(group_id)
    user_id = _get_user(authorization)
    add_to_watchlist(user_id, ticker, group_id)
    return {"ok": True}


@router.delete("/{ticker}")
def remove_watch(ticker: str, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    remove_from_watchlist(user_id, ticker)
    return {"ok": True}


class NoteBody(BaseModel):
    note: str


@router.patch("/{ticker}/note")
def set_note(ticker: str, body: NoteBody, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    update_watchlist_note(user_id, ticker, body.note)
    return {"ok": True}


class GroupBody(BaseModel):
    group_id: int


@router.patch("/{ticker}/group")
def set_group(ticker: str, body: GroupBody, authorization: str | None = Header(None)):
    _check_group_id(body.group_id)
    user_id = _get_user(authorization)
    update_watchlist_group(user_id, ticker, body.group_id)
    return {"ok": True}
