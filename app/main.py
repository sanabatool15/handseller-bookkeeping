from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import close_client, init_client
from app.routers import expenses, reports, sales


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_client()
    yield
    close_client()


app = FastAPI(
    title="Handseller Bookkeeping API",
    description="Internal bookkeeping backend for handseller sales and expense tracking.",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sales.router)
app.include_router(expenses.router)
app.include_router(reports.router)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}
