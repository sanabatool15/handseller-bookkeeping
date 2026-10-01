"""Shared repository helpers (SQL Server / T-SQL via core.db.Db).

CRITICAL invariant enforced across this whole layer: every read/update/delete
on a tenant-scoped table filters by BOTH `id` and `org_id` in the same SQL
statement, so a caller can never "check ownership then fetch by id alone" (the
classic IDOR / check-then-fetch vulnerability). `tests/unit/test_repository_sql_rules.py`
enforces this statically for every statement in `repository/*.py`.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Optional

from core.db import Db, UniqueViolationError, transaction  # noqa: F401  (re-exported for services)

# Services catch this instead of importing driver/SQL details.
DuplicateRecordError = UniqueViolationError


class RepositoryError(Exception):
    """Raised when a repository call is misused or returns an unexpected shape."""


# Table names are NEVER interpolated into SQL: each allowed table has its own literal statement,
# and anything not in this allow-list is rejected before any SQL is built.
_OWNERSHIP_SQL = {
    "users": "SELECT 1 AS ok FROM users WHERE id = ? AND org_id = ?",
    "sales": "SELECT 1 AS ok FROM sales WHERE id = ? AND org_id = ?",
    "expenses": "SELECT 1 AS ok FROM expenses WHERE id = ? AND org_id = ?",
    "agent_jobs": "SELECT 1 AS ok FROM agent_jobs WHERE id = ? AND org_id = ?",
    "products": "SELECT 1 AS ok FROM products WHERE id = ? AND org_id = ?",
    "customers": "SELECT 1 AS ok FROM customers WHERE id = ? AND org_id = ?",
}


def get_ownership(db: Db, *, table: str, record_id: str, org_id: str) -> bool:
    """Does `table` contain a row with this id that belongs to this org? (id AND org_id, one statement.)

    `table` must be one of the allow-listed tenant tables; any other value raises RepositoryError.
    """
    try:
        sql = _OWNERSHIP_SQL[table]
    except (KeyError, TypeError) as exc:
        raise RepositoryError(f"ownership check not supported for table {table!r}") from exc
    return db.query_one(sql, (record_id, org_id)) is not None


def month_range(year: int, month: int) -> tuple[dt.date, dt.date]:
    """[first day of month, first day of next month) for a half-open SQL date range."""
    start = dt.date(year, month, 1)
    end = dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    return start, end


def today_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def to_json(value: Any) -> Optional[str]:
    """Serialise a dict for an nvarchar(max) JSON column (None stays NULL)."""
    return None if value is None else json.dumps(value, default=str)


def from_json(value: Any) -> Any:
    """Parse an nvarchar(max) JSON column back into Python (NULL stays None)."""
    if value is None or not isinstance(value, str):
        return value
    return json.loads(value)


def clamp_page(limit: int, offset: int) -> tuple[int, int]:
    """OFFSET must be >= 0 and FETCH NEXT must be >= 1 in T-SQL."""
    return max(1, int(limit)), max(0, int(offset))
