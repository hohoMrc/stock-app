from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from app.routers.auth import verify_token
from app.db import get_watchlist, add_to_watchlist, remove_from_watchlist, update_watchlist_note

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _get_user(authorization: str | None) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="請先登入")
    return verify_token(authorization[7:])


@router.get("")
def list_watchlist(authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    items = get_watchlist(user_id)
    return {
        "tickers": [i["ticker"] for i in items],
        "notes": {i["ticker"]: i["note"] for i in items},
    }


@router.post("/{ticker}")
def add_watch(ticker: str, authorization: str | None = Header(None)):
    user_id = _get_user(authorization)
    add_to_watchlist(user_id, ticker)
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
