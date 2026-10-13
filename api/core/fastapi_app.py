"""FastAPI application entrypoint.

Wires: routers, auth + idempotency middleware, CORS, lifespan (SQL Server
reachability probe).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.config import get_settings
from middleware.auth import AuthMiddleware
from middleware.idempotency import IdempotencyMiddleware
from middleware.request_id import RequestIdMiddleware
from routers import (auth_router, cash_router, customers_router, db_lab_router, expenses_router, products_router,
                     sales_router, txn_log_router)
from services import health_service

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger("handseller.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Probe SQL Server once so a bad connection string is visible in the startup log at once
    # (not fatal: the DB may come up later and each request opens its own connection).
    db_status = await run_in_threadpool(health_service.check_database)
    if db_status == "ok":
        logger.info("SQL Server connection OK")
    else:
        logger.warning("SQL Server not reachable at startup (%s) - requests will fail until it is", db_status)
    yield


app = FastAPI(title="Handseller Bookkeeping Backend", version="0.1.0", lifespan=lifespan)

# Order matters: Starlette runs middleware added last FIRST. We want Auth to
# run before Idempotency (idempotency cache keys are scoped per-org, which
# requires request.state.user to already be populated), so add Idempotency
# first and Auth second. CORSMiddleware must be added LAST (outermost) so it
# can intercept and answer an OPTIONS preflight request before AuthMiddleware
# ever sees it -- otherwise every preflight to an authenticated route gets
# rejected with 401 before CORS headers are attached, which browsers report
# as a CORS failure even though the real cause is auth running too early.
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestIdMiddleware)  # outside Auth: every response (also 401) carries X-Request-ID
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    content = {"detail": exc.detail}
    request_id = getattr(request.state, "request_id", None)
    # Only for 409 (e.g. insufficient stock): lets the client find the log of the refused request on the Activity page.
    # Other errors keep their exact body (the 404 bodies of a foreign and of an unknown id must stay identical).
    if request_id and exc.status_code == 409:
        content["request_id"] = request_id
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    # ServerErrorMiddleware answers outside RequestIdMiddleware, so the header is added here for 500s.
    headers = {"X-Request-ID": request.state.request_id} if getattr(request.state, "request_id", None) else None
    return JSONResponse(status_code=500, content={"detail": "Internal server error"}, headers=headers)


@app.get("/")
def root():
    return {"service": "handseller-bookkeeping", "status": "ok"}


@app.get("/health")
async def health():
    checks = {}
    checks["database"] = await run_in_threadpool(health_service.check_database)
    return {"status": "ok", "checks": checks}


app.include_router(auth_router.router)
app.include_router(sales_router.router)
app.include_router(expenses_router.router)
app.include_router(products_router.router)
app.include_router(customers_router.router)
app.include_router(cash_router.router)
app.include_router(txn_log_router.router)
app.include_router(db_lab_router.router)
