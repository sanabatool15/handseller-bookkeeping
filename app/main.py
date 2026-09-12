"""FastAPI application entrypoint: wires routers, middleware, and CORS."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.middleware.idempotency import IdempotencyMiddleware
from app.routers import agent, expenses, reports, sales


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the Supabase client on startup (lazy singleton via get_client()).
    from app.core.db import get_client

    get_client()
    yield


app = FastAPI(
    title="Handseller Bookkeeping API",
    description="Multi-tenant bookkeeping backend with Supabase, idempotent mutations, and an AI financial advisor.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(IdempotencyMiddleware)

app.include_router(sales.router)
app.include_router(expenses.router)
app.include_router(reports.router)
app.include_router(agent.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """Turn pydantic validation failures into explicit 422 messages listing
    the missing/invalid fields."""
    errors = [
        {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": "Validation failed", "errors": errors})


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
