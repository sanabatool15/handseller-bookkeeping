"""Read-only API over the transaction event log (Activity page). Org-scoped: a tenant only ever sees its own events."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.db import Db
from core.security import CurrentUser
from routers.deps import DB, get_current_user
from services import txn_log_service

router = APIRouter(prefix="/db-logs", tags=["db-logs"])


@router.get("")
def list_events(
    request_id: str | None = None, operation: str | None = None, step: str | None = None, status: str | None = None,
    limit: int = 100, offset: int = 0, order: str = "desc",
    user: CurrentUser = Depends(get_current_user), db: Db = DB,
):
    """Events (newest first by default; `order=asc` for a timeline) filtered by request_id/operation/step/status."""
    try:
        return txn_log_service.list_events(
            db, org_id=user.org_id, request_id=request_id, operation=operation, step=step, status=status,
            limit=limit, offset=offset, order=order,
        )
    except txn_log_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/requests")
def list_requests(
    request_id: str | None = None, operation: str | None = None, outcome: str | None = None, limit: int = 50, offset: int = 0,
    user: CurrentUser = Depends(get_current_user), db: Db = DB,
):
    """One row per request_id: first/last timestamp, final outcome, retries, deadlocks, duration."""
    try:
        return txn_log_service.list_requests(
            db, org_id=user.org_id, request_id=request_id, operation=operation, outcome=outcome, limit=limit, offset=offset,
        )
    except txn_log_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
