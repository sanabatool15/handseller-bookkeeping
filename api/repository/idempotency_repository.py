"""Idempotency keys in SQL Server (replaces Redis). Always used on a SEPARATE autocommit connection."""
from __future__ import annotations

from typing import Any, Optional

from core.db import Db, UniqueViolationError

# Rows that are too old (done: older than the TTL; processing: older than the lock time) count as "not there".
_DELETE_EXPIRED = (
    "DELETE FROM idempotency_keys WHERE org_scope = ? AND idem_key = ? AND "
    "((state = N'done' AND created_at < DATEADD(SECOND, -?, SYSUTCDATETIME())) "
    "OR (state = N'processing' AND created_at < DATEADD(SECOND, -?, SYSUTCDATETIME())))"
)
_INSERT = "INSERT INTO idempotency_keys (org_scope, idem_key, state) VALUES (?, ?, N'processing')"
_GET = "SELECT state, status_code, response_body FROM idempotency_keys WHERE org_scope = ? AND idem_key = ?"
_FINISH = (
    "UPDATE idempotency_keys SET state = N'done', status_code = ?, response_body = ? "
    "WHERE org_scope = ? AND idem_key = ?"
)
_ABANDON = "DELETE FROM idempotency_keys WHERE org_scope = ? AND idem_key = ? AND state = N'processing'"


def begin(db: Db, *, org_scope: str, idem_key: str, ttl_seconds: int, lock_seconds: int) -> tuple[str, Optional[dict[str, Any]]]:
    """Try to claim the key. Returns ("new", None) when this request may run, ("cached", row) when an answer is saved,
    ("in_progress", None) when another request with the same key is running."""
    db.execute(_DELETE_EXPIRED, (org_scope, idem_key, ttl_seconds, lock_seconds))
    for _ in range(2):
        try:
            db.execute(_INSERT, (org_scope, idem_key))
            return "new", None
        except UniqueViolationError:
            row = db.query_one(_GET, (org_scope, idem_key))
            if row is None:  # deleted in between: try to claim again
                continue
            return ("cached", row) if row["state"] == "done" else ("in_progress", None)
    return "in_progress", None


def finish(db: Db, *, org_scope: str, idem_key: str, status_code: int, response_body: str) -> None:
    db.execute(_FINISH, (status_code, response_body, org_scope, idem_key))


def abandon(db: Db, *, org_scope: str, idem_key: str) -> None:
    db.execute(_ABANDON, (org_scope, idem_key))
