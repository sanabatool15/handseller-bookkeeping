"""Idempotency keys (SQL Server, no Redis). Each call uses its own short autocommit connection, so a saved key is
never rolled back together with the business transaction."""
from __future__ import annotations

import json
from typing import Any, Optional

from core import clients
from repository import idempotency_repository

LOCK_SECONDS = 30  # a request still "processing" after this long is treated as dead


def _with_db(fn):
    db = clients.get_autocommit_connection()
    try:
        return fn(db)
    finally:
        db.close()


def begin(org_scope: str, idem_key: str, ttl_seconds: int) -> tuple[str, Optional[dict[str, Any]]]:
    """("new", None) | ("cached", {"status_code": int, "body": any}) | ("in_progress", None)"""
    state, row = _with_db(lambda db: idempotency_repository.begin(
        db, org_scope=org_scope, idem_key=idem_key, ttl_seconds=ttl_seconds, lock_seconds=LOCK_SECONDS))
    if state == "cached":
        return "cached", {"status_code": row["status_code"], "body": json.loads(row["response_body"] or "null")}
    return state, None


def finish(org_scope: str, idem_key: str, status_code: int, body: Any) -> None:
    _with_db(lambda db: idempotency_repository.finish(
        db, org_scope=org_scope, idem_key=idem_key, status_code=status_code, response_body=json.dumps(body, default=str)))


def abandon(org_scope: str, idem_key: str) -> None:
    _with_db(lambda db: idempotency_repository.abandon(db, org_scope=org_scope, idem_key=idem_key))
