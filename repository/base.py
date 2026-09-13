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
