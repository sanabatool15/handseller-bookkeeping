"""FastAPI application entrypoint: wires routers, CORS, and error handling."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db.client import close_client, init_client
from app.routers import expenses, orgs, reports, sales


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_client()
    yield
    close_client()


app = FastAPI(
    title="Handseller Bookkeeping API",
    description=(
        "Backend for a handseller bookkeeping application: daily sales/expense "
        "tracking, monthly financial reports, and expense analytics, backed by "
        "Supabase with strict per-org ownership checks."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Maps domain errors (NotFound/Forbidden/ValidationApp) to explicit HTTP responses."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Turns Pydantic validation errors into explicit 'what is missing' messages."""
    errors = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query"))
        errors.append(f"Field '{loc}': {err.get('msg')}")
    return JSONResponse(
        status_code=422,
        content={"detail": errors or "Invalid request body."},
    )


app.include_router(orgs.router)
app.include_router(sales.router)
app.include_router(expenses.router)
app.include_router(reports.router)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
