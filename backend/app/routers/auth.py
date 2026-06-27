import os
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from jose import jwt
from passlib.context import CryptContext
from app.db import create_user, get_user_by_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.environ.get("JWT_SECRET", "change-me-in-production")
ALGORITHM  = "HS256"
TOKEN_DAYS = 30


def _make_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=TOKEN_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 無效或已過期")


class RegisterBody(BaseModel):
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
def register(body: RegisterBody):
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密碼至少 6 個字元")
    if get_user_by_email(body.email):
        raise HTTPException(status_code=400, detail="此 Email 已被註冊")
    user_id = create_user(body.email, _pwd.hash(body.password))
    return {"token": _make_token(user_id), "email": body.email}


@router.post("/login")
def login(body: LoginBody):
    user = get_user_by_email(body.email)
    if not user or not _pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email 或密碼錯誤")
    return {"token": _make_token(user["id"]), "email": user["email"]}
