"""Liveness/readiness checks used by startup and GET /health. No SQL here: goes through the repository."""
from __future__ import annotations

from core.clients import db_session
from repository import health_repository


def check_database() -> str:
    """Return "ok" or "error: <reason>" after a trivial round trip to SQL Server."""
    try:
        with db_session() as db:
            return "ok" if health_repository.ping(db) else "error: unexpected ping result"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
