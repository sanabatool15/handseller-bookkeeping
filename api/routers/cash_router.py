from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from core.db import Db

from core.security import CurrentUser
from routers.deps import DB, get_current_user
from services import cash_service

router = APIRouter(prefix="/cash", tags=["cash"])


@router.get("/balance")
def get_balance(user: CurrentUser = Depends(get_current_user), db: Db = DB):
    return cash_service.get_balance(db, org_id=user.org_id)


@router.get("/ledger")
def list_ledger(
    limit: int = 100, offset: int = 0, entry_type: str | None = None,
    date_from: dt.date | None = Query(default=None, alias="from"), date_to: dt.date | None = Query(default=None, alias="to"),
    user: CurrentUser = Depends(get_current_user), db: Db = DB,
):
    try:
        return cash_service.list_ledger(
            db, org_id=user.org_id, limit=limit, offset=offset, entry_type=entry_type, date_from=date_from, date_to=date_to,
        )
    except cash_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/summary")
def get_summary(year: int | None = None, month: int | None = None, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    try:
        return cash_service.get_summary(db, org_id=user.org_id, year=year, month=month)
    except cash_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
