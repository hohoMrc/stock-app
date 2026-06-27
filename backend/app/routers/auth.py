import os
import hashlib
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from jose import jwt
from app.db import create_user, get_user_by_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

SECRET_KEY = os.environ.get("JWT_SECRET", "change-me-in-production")
ALGORITHM  = "HS256"
TOKEN_DAYS = 30


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    return f"{salt}:{dk.hex()}"


def _verify_password(password: str, hashed: str) -> bool:
    try:
        salt, dk_hex = hashed.split(":", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


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
    user_id = create_user(body.email, _hash_password(body.password))
    return {"token": _make_token(user_id), "email": body.email}


@router.post("/login")
def login(body: LoginBody):
    user = get_user_by_email(body.email)
    if not user or not _verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email 或密碼錯誤")
    return {"token": _make_token(user["id"]), "email": user["email"]}
