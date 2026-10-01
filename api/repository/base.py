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

from core.db import Db, ForeignKeyViolationError, UniqueViolationError, transaction  # noqa: F401  (re-exported for services)

# Services catch these instead of importing driver/SQL details. Same pattern for both: core.db maps the engine
# error (2627/2601 resp. 547 REFERENCE/FOREIGN KEY) to a typed exception, the repository lets it propagate.
DuplicateRecordError = UniqueViolationError
RecordInUseError = ForeignKeyViolationError  # deleting a row that other rows still reference (e.g. a product with sales)


class RepositoryError(Exception):
    """Raised when a repository call is misused or returns an unexpected shape."""


# Error numbers raised by the stored procedures themselves (business outcomes, not engine errors):
# 50001 insufficient stock, 50002 product, 50003 validation, 50004 customer, 50005 org, 50006 sale,
# 50007 expense not found, 50008 not allowed.
BUSINESS_ERRORS = frozenset({50001, 50002, 50003, 50004, 50005, 50006, 50007, 50008})


class ProcedureError(RuntimeError):
    """The stored procedure rolled back because of an ENGINE error (deadlock 1205, constraint 547, ...).

    The text always contains the error number so core.db.is_deadlock() recognises a deadlock victim."""

    def __init__(self, error_number: int | None, message: str | None):
        self.error_number = error_number
        super().__init__(f"stored procedure failed with error {error_number}: {message}")


def call_procedure(db: Db, sql: str, params: tuple, *, name: str) -> dict[str, Any]:
    """Run ONE `EXEC dbo.usp_X ...; SELECT <outputs>` batch and return its OUTPUT row.

    A driver error or an ENGINE error reported by the procedure (rolled_back with a non-business error number)
    rolls the connection back and raises (ProcedureError for the latter) so the caller's deadlock retry can re-run
    the whole unit of work. Business outcomes (statuses, 5000x numbers) are returned for the caller to interpret."""
    try:
        row = db.query_one(sql, params)
    except Exception:
        db.rollback()  # e.g. a deadlock raised by the driver itself: leave a clean connection for the retry
        raise
    if row is None:
        db.rollback()
        raise ProcedureError(None, f"{name} returned no result")
    if row["status"] == "rolled_back" and row["error_number"] not in BUSINESS_ERRORS:
        db.rollback()
        raise ProcedureError(row["error_number"], row["message"])
    return row


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
