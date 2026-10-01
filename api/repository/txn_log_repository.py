"""Transaction event log repository (SQL Server / T-SQL). Every statement carries org_id.

`insert_events` must be called with a SEPARATE AUTOCOMMIT connection (core.clients.get_autocommit_connection) so the rows
survive a rollback of the business transaction (specs/15). The reads use the normal request connection.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from core.db import Db
from repository.base import clamp_page

STEPS = (
    "txn_started", "lock_wait_suspected", "deadlock_1205_caught", "lock_timeout_caught",
    "retry_triggered", "rolled_back", "committed", "business_rejected",
)
_COLS = (
    "id, request_id, org_id, operation, step, isolation_level, status, error_number, message, duration_ms, retry_no, created_at"
)

# One statement for the whole batch. org_id is a BOUND PARAMETER, never read from the JSON, so a caller cannot write
# events for another org. `seq` keeps the identity values in event order (INSERT ... SELECT ... ORDER BY).
# created_at arrives as naive-UTC text (datetime2) and is declared UTC with TODATETIMEOFFSET.
_INSERT_BATCH = (
    "INSERT INTO txn_log (request_id, org_id, operation, step, isolation_level, status, error_number, message, "
    "duration_ms, retry_no, created_at) "
    "SELECT j.request_id, ?, j.operation, j.step, j.isolation_level, j.status, j.error_number, j.message, "
    "j.duration_ms, j.retry_no, TODATETIMEOFFSET(j.created_at, '+00:00') "
    "FROM OPENJSON(?) WITH (seq int '$.seq', request_id nvarchar(64) '$.request_id', operation nvarchar(60) '$.operation', "
    "step nvarchar(40) '$.step', isolation_level nvarchar(24) '$.isolation_level', status nvarchar(20) '$.status', "
    "error_number int '$.error_number', message nvarchar(400) '$.message', duration_ms int '$.duration_ms', "
    "retry_no int '$.retry_no', created_at datetime2(6) '$.created_at') AS j "
    "ORDER BY j.seq"
)

# Optional filters stay bound parameters: `(CAST(? AS <type>) IS NULL OR col = ?)` is a no-op when the parameter is NULL,
# so the statement text is static (nothing is assembled from the filters).
_EVENT_FILTERS = (
    "WHERE org_id = ? "
    "AND (CAST(? AS nvarchar(64)) IS NULL OR request_id = ?) "
    "AND (CAST(? AS nvarchar(60)) IS NULL OR operation = ?) "
    "AND (CAST(? AS nvarchar(40)) IS NULL OR step = ?) "
    "AND (CAST(? AS nvarchar(20)) IS NULL OR status = ?) "
)
_LIST_NEWEST = (
    "SELECT " + _COLS + " FROM txn_log " + _EVENT_FILTERS
    + "ORDER BY created_at DESC, id DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)
_LIST_OLDEST = (
    "SELECT " + _COLS + " FROM txn_log " + _EVENT_FILTERS
    + "ORDER BY created_at ASC, id ASC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)

# One row per request_id (GROUP BY). `outcome` is the final outcome of the request:
#   committed          the request transaction committed, no deadlock retry happened
#   deadlock_retried   it committed after at least one retry_triggered (deadlock victim that succeeded on retry)
#   rolled_back        the request transaction was rolled back (engine error, exhausted retries, failure after the work)
#   rejected           a business rule refused it (e.g. insufficient stock) - not an engine rollback
#   in_progress        none of the above yet (or the final event was lost)
_REQUESTS = (
    "SELECT * FROM ("
    "SELECT request_id, MAX(operation) AS operation, MIN(created_at) AS first_at, MAX(created_at) AS last_at, "
    "COUNT(*) AS event_count, "
    "SUM(CASE WHEN step = 'retry_triggered' THEN 1 ELSE 0 END) AS retries, "
    "SUM(CASE WHEN step IN ('deadlock_1205_caught', 'lock_timeout_caught') THEN 1 ELSE 0 END) AS deadlocks, "
    "SUM(CASE WHEN step = 'lock_wait_suspected' THEN 1 ELSE 0 END) AS lock_waits_suspected, "
    "COALESCE(MAX(duration_ms), 0) AS duration_ms, MAX(isolation_level) AS isolation_level, "
    "CASE "
    "WHEN MAX(CASE WHEN step = 'committed' THEN 1 ELSE 0 END) = 1 "
    "AND SUM(CASE WHEN step = 'retry_triggered' THEN 1 ELSE 0 END) > 0 THEN 'deadlock_retried' "
    "WHEN MAX(CASE WHEN step = 'committed' THEN 1 ELSE 0 END) = 1 THEN 'committed' "
    "WHEN MAX(CASE WHEN step = 'rolled_back' THEN 1 ELSE 0 END) = 1 THEN 'rolled_back' "
    "WHEN MAX(CASE WHEN step = 'business_rejected' THEN 1 ELSE 0 END) = 1 THEN 'rejected' "
    "ELSE 'in_progress' END AS outcome "
    "FROM txn_log WHERE org_id = ? "
    "AND (CAST(? AS nvarchar(64)) IS NULL OR request_id = ?) "
    "AND (CAST(? AS nvarchar(60)) IS NULL OR operation = ?) "
    "GROUP BY request_id"
    ") AS r WHERE (CAST(? AS nvarchar(20)) IS NULL OR r.outcome = ?) "
    "ORDER BY r.last_at DESC, r.request_id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)


def insert_events(db: Db, *, org_id: str, events: list[dict[str, Any]]) -> int:
    """Append a batch of events (dicts with the txn_log columns except id/org_id) in ONE statement; returns rows inserted.
    `db` must be a separate autocommit connection."""
    if not events:
        return 0
    payload = []
    for seq, e in enumerate(events):
        if e["step"] not in STEPS:
            raise ValueError(f"unknown txn_log step {e['step']!r}")
        payload.append({**e, "seq": seq})
    return db.execute(_INSERT_BATCH, (org_id, json.dumps(payload, default=str)))


def list_events(
    db: Db, *, org_id: str, request_id: Optional[str] = None, operation: Optional[str] = None, step: Optional[str] = None,
    status: Optional[str] = None, limit: int = 100, offset: int = 0, oldest_first: bool = False,
) -> list[dict[str, Any]]:
    limit, offset = clamp_page(limit, offset)
    params = (org_id, request_id, request_id, operation, operation, step, step, status, status, offset, limit)
    return db.query(_LIST_OLDEST if oldest_first else _LIST_NEWEST, params)


def list_requests(
    db: Db, *, org_id: str, request_id: Optional[str] = None, operation: Optional[str] = None,
    outcome: Optional[str] = None, limit: int = 50, offset: int = 0,
) -> list[dict[str, Any]]:
    """One row per request_id, newest activity first (GROUP BY in SQL)."""
    limit, offset = clamp_page(limit, offset)
    return db.query(_REQUESTS, (org_id, request_id, request_id, operation, operation, outcome, outcome, offset, limit))


def get_isolation_level(db: Db) -> str:
    """Effective isolation level of `db`'s session (so services need no SQL / Db internals)."""
    return db.get_isolation_level()
