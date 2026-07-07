import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from app.routers import stocks
from app.routers.auth import router as auth_router
from app.routers.watchlist import router as watchlist_router
from app.routers.admin import router as admin_router
from app.routers.futures import router as futures_router
from app.routers.futures_ws import router as futures_ws_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db import init_db
    init_db()
    def _bg_init():
        from app.services.stock_data import _get_fugle
        _get_fugle()
    threading.Thread(target=_bg_init, daemon=True).start()
    yield


app = FastAPI(title="台股分析工具", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://stock-app-lilac-nine.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stocks.router)
app.include_router(auth_router)
app.include_router(watchlist_router)
app.include_router(admin_router)
app.include_router(futures_router)
app.include_router(futures_ws_router)


@app.get("/")
async def root():
    return {"message": "台股分析 API 正常運作中"}
