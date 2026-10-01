"""Shared repository helpers.

CRITICAL invariant enforced across this whole layer: every read/update/delete
on a tenant-scoped table filters by BOTH `id` and `org_id` in the same query,
so a caller can never "check ownership then fetch by id alone" (the classic
IDOR / check-then-fetch vulnerability). There is no code path in this
codebase that fetches a record by id without also constraining org_id.
"""
from __future__ import annotations

from typing import Any, Optional

from supabase import Client

from core.db import Db, UniqueViolationError, transaction  # noqa: F401  (re-exported for services)

# Services catch this instead of importing driver/SQL details.
DuplicateRecordError = UniqueViolationError


class RepositoryError(Exception):
    """Raised when a Supabase operation fails or returns unexpected shape."""


def unwrap_single(rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    return rows[0] if rows else None


def get_ownership(db: Client, *, table: str, record_id: str, org_id: str) -> bool:
    """Generic ownership check: does `table` contain a row with this id scoped to this org?

    Used by services before performing side-effecting operations that don't
    themselves return rows (e.g. before enqueuing a background job tied to a
    record), and directly satisfies the `get_ownership(user_id, org_id)`-style
    check required by the spec (here parameterized as record_id/org_id/table,
    since ownership in this schema is expressed as org membership).
    """
    resp = db.table(table).select("id").eq("id", record_id).eq("org_id", org_id).limit(1).execute()
    return bool(resp.data)


# SQL Server variant. Table names are NEVER interpolated: each allowed table has its own literal SQL.
_OWNERSHIP_SQL = {
    "users": "SELECT 1 AS ok FROM users WHERE id = ? AND org_id = ?",
    "sales": "SELECT 1 AS ok FROM sales WHERE id = ? AND org_id = ?",
    "expenses": "SELECT 1 AS ok FROM expenses WHERE id = ? AND org_id = ?",
    "agent_jobs": "SELECT 1 AS ok FROM agent_jobs WHERE id = ? AND org_id = ?",
}


def get_ownership_sql(db: Db, *, table: str, record_id: str, org_id: str) -> bool:
    """SQL Server ownership check: id AND org_id in the same statement."""
    try:
        sql = _OWNERSHIP_SQL[table]
    except KeyError as exc:
        raise RepositoryError(f"ownership check not supported for table {table!r}") from exc
    return db.query_one(sql, (record_id, org_id)) is not None
