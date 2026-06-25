import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from app.routers import stocks

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 背景執行緒初始化 Fugle，避免阻塞 health check 導致部署 timeout
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


@app.get("/")
async def root():
    return {"message": "台股分析 API 正常運作中"}
