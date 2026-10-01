"""Cash balance / ledger reads. Cash is only WRITTEN by the sale procedures (see specs/14, specs/15)."""
from __future__ import annotations

from typing import Any

from core.db import Db

from repository import cash_repository


def get_balance(db: Db, *, org_id: str) -> dict[str, Any]:
    return cash_repository.get_balance(db, org_id=org_id)


def list_ledger(db: Db, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    return cash_repository.list_ledger(db, org_id=org_id, limit=limit, offset=offset)
