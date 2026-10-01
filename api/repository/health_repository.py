"""Connectivity probe (no tenant data)."""
from __future__ import annotations

from core.db import Db

_PING = "SELECT 1 AS ok"


def ping(db: Db) -> bool:
    """True if SQL Server answers a trivial query."""
    row = db.query_one(_PING)
    return bool(row and row.get("ok") == 1)
