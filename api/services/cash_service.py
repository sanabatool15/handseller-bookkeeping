"""Cash balance / ledger / monthly summary reads. Cash is only WRITTEN by the sale/expense procedures (specs/14, specs/15)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from core.db import Db

from repository import base as repo_base
from repository import cash_repository

ENTRY_TYPES = ("sale", "sale_void", "expense", "expense_void", "adjustment")


class ValidationError(Exception):
    pass


def get_balance(db: Db, *, org_id: str) -> dict[str, Any]:
    return cash_repository.get_balance(db, org_id=org_id)


def list_ledger(
    db: Db, *, org_id: str, limit: int = 100, offset: int = 0, entry_type: str | None = None,
    date_from: dt.date | None = None, date_to: dt.date | None = None,
) -> list[dict[str, Any]]:
    """Ledger entries, newest first. Filters: `entry_type` (one of ENTRY_TYPES), `date_from`/`date_to` (inclusive, by entry_date)."""
    if entry_type is not None and entry_type not in ENTRY_TYPES:
        raise ValidationError(f"entry_type must be one of {', '.join(ENTRY_TYPES)}")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValidationError("'from' must not be after 'to'")
    return cash_repository.list_ledger(
        db, org_id=org_id, limit=limit, offset=offset, entry_type=entry_type, date_from=date_from, date_to=date_to,
    )


def get_summary(db: Db, *, org_id: str, year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Summary of one calendar month (default: the current UTC month). `by_type` always lists every entry type (net amount, 0.0 when none)."""
    today = repo_base.today_utc()
    year = today.year if year is None else year
    month = today.month if month is None else month
    if not 1 <= month <= 12:
        raise ValidationError("month must be between 1 and 12")
    if not 2000 <= year <= 2100:
        raise ValidationError("year must be between 2000 and 2100")
    summary = cash_repository.get_month_summary(db, org_id=org_id, year=year, month=month)
    summary["by_type"] = {t: summary["by_type"].get(t, 0.0) for t in ENTRY_TYPES}
    return {"year": year, "month": month, **summary}
