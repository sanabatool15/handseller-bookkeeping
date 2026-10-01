from __future__ import annotations

from fastapi import APIRouter, Depends
from core.db import Db

from core.security import CurrentUser
from routers.deps import get_current_user, get_db
from services import cash_service

router = APIRouter(prefix="/cash", tags=["cash"])


@router.get("/balance")
def get_balance(user: CurrentUser = Depends(get_current_user), db: Db = Depends(get_db)):
    return cash_service.get_balance(db, org_id=user.org_id)


@router.get("/ledger")
def list_ledger(limit: int = 100, offset: int = 0, user: CurrentUser = Depends(get_current_user), db: Db = Depends(get_db)):
    return cash_service.list_ledger(db, org_id=user.org_id, limit=limit, offset=offset)
