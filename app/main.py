"""FastAPI application entrypoint for the handseller bookkeeping backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.supabase_client import close_supabase, init_supabase
from app.routers import (
    customers,
    expenses,
    invoices,
    payments,
    products,
    reports,
    sales,
    sellers,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: establish the Supabase client connection.
    init_supabase()
    yield
    # Shutdown: release the Supabase client reference.
    close_supabase()


settings = get_settings()

app = FastAPI(
    title="Handseller Bookkeeping API",
    description="Backend API for tracking sellers, customers, products, sales, "
    "payments, expenses, and invoices for a handseller business.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sellers.router)
app.include_router(customers.router)
app.include_router(products.router)
app.include_router(sales.router)
app.include_router(payments.router)
app.include_router(expenses.router)
app.include_router(invoices.router)
app.include_router(reports.router)


@app.get("/", tags=["health"])
def root():
    return {"status": "ok", "service": "handseller-bookkeeping-api"}


@app.get("/health", tags=["health"])
def health():
    return {"status": "healthy"}
