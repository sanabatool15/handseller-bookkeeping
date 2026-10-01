"""DB Lab routes (DEMO ONLY). With ENABLE_DB_LAB=false every route except GET /db-lab/status answers 404."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import Db
from core.security import CurrentUser
from routers.deps import DB, get_current_user
from services import db_lab_service

router = APIRouter(prefix="/db-lab", tags=["db-lab (demo only)"])

IsolationLevel = Literal["READ UNCOMMITTED", "READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE", "SNAPSHOT"]
DelaySeconds = Literal[0, 1, 2, 3, 4, 5]


def require_lab() -> None:
    try:
        db_lab_service.ensure_enabled()
    except db_lab_service.DisabledError as exc:
        raise HTTPException(status_code=404, detail="Not Found") from exc


class RaceSaleIn(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1, le=db_lab_service.MAX_QUANTITY)
    clients: int = Field(default=2, ge=2, le=db_lab_service.MAX_CLIENTS)
    mode: Literal["safe", "unsafe"] = "safe"
    isolation_level: IsolationLevel = "READ COMMITTED"
    delay_seconds: DelaySeconds = 1
    restore_stock: bool = True


class DeadlockIn(BaseModel):
    product_a: str
    product_b: str
    delay_seconds: DelaySeconds = 1


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, db_lab_service.NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


_ERRORS = (db_lab_service.ValidationError, db_lab_service.NotFoundError)


@router.get("/status")
def lab_status(user: CurrentUser = Depends(get_current_user)):
    """The one lab route that never 404s: tells the UI whether to show the DB Lab."""
    return db_lab_service.status()


@router.post("/race-sale", dependencies=[Depends(require_lab)])
def race_sale(payload: RaceSaleIn, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    try:
        return db_lab_service.race_sale(
            db, org_id=user.org_id, product_id=payload.product_id, quantity=payload.quantity, clients_n=payload.clients,
            mode=payload.mode, isolation_level=payload.isolation_level, delay_seconds=payload.delay_seconds,
            restore_stock=payload.restore_stock,
        )
    except _ERRORS as exc:
        raise _http(exc) from exc


@router.post("/deadlock", dependencies=[Depends(require_lab)])
def deadlock(payload: DeadlockIn, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    try:
        return db_lab_service.deadlock(
            db, org_id=user.org_id, product_a=payload.product_a, product_b=payload.product_b,
            delay_seconds=payload.delay_seconds, fixed=False,
        )
    except _ERRORS as exc:
        raise _http(exc) from exc


@router.post("/deadlock-fixed", dependencies=[Depends(require_lab)])
def deadlock_fixed(payload: DeadlockIn, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    try:
        return db_lab_service.deadlock(
            db, org_id=user.org_id, product_a=payload.product_a, product_b=payload.product_b,
            delay_seconds=payload.delay_seconds, fixed=True,
        )
    except _ERRORS as exc:
        raise _http(exc) from exc
