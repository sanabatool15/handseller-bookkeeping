"""FastAPI application entrypoint.

Wires: routers, auth + idempotency middleware, CORS, lifespan (Supabase +
Redis client setup/teardown), and mounts the Inngest FastAPI handler.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.clients import close_clients, get_redis, get_supabase
from app.config import get_settings
from middleware.auth import AuthMiddleware
from middleware.idempotency import IdempotencyMiddleware
from routers import agent_jobs_router, auth_router, expenses_router, sales_router

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger("handseller.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eagerly initialize clients so a bad config fails fast at startup.
    get_supabase()
    redis = get_redis()
    try:
        await redis.ping()
        logger.info("Redis connection OK")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis not reachable at startup (%s) — will retry lazily per-request", exc)

    yield

    await close_clients()


app = FastAPI(title="Handseller Bookkeeping Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Order matters: Starlette runs middleware added last FIRST. We want Auth to
# run before Idempotency (idempotency cache keys are scoped per-org, which
# requires request.state.user to already be populated), so add Idempotency
# first and Auth last.
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(AuthMiddleware)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/")
def root():
    return {"service": "handseller-bookkeeping", "status": "ok"}


@app.get("/health")
async def health():
    checks = {"redis": "unknown", "supabase": "unknown"}
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc}"
    try:
        get_supabase()
        checks["supabase"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["supabase"] = f"error: {exc}"
    return {"status": "ok", "checks": checks}


app.include_router(auth_router.router)
app.include_router(sales_router.router)
app.include_router(expenses_router.router)
app.include_router(agent_jobs_router.router)

# --- Inngest FastAPI handler mount ---
# Assumption: pinned against inngest==0.5.x's `inngest.fast_api.serve` helper,
# which registers the required PUT/POST/GET routes at `/api/inngest` for the
# Inngest dev server / cloud to sync and invoke functions. See README.
try:
    import inngest.fast_api

    from jobs.financial_agent_job import ALL_FUNCTIONS
    from jobs.inngest_client import inngest_client

    inngest.fast_api.serve(app, inngest_client, ALL_FUNCTIONS, serve_path="/api/inngest")
except Exception as exc:  # noqa: BLE001
    logger.warning("Could not mount Inngest handler (%s) — background jobs will not run until fixed", exc)
