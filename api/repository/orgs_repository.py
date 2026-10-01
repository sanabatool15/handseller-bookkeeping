"""orgs table access (SQL Server / T-SQL via core.db.Db)."""
from __future__ import annotations

from typing import Any, Optional

from core.db import Db

# orgs has an AFTER UPDATE trigger => OUTPUT must go INTO a table variable (SQL Server error 334).
_INSERT = (
    "SET NOCOUNT ON; "
    "DECLARE @o TABLE (id uniqueidentifier, name nvarchar(200), owner_id uniqueidentifier, "
    "created_at datetimeoffset, updated_at datetimeoffset); "
    "INSERT INTO orgs (name, owner_id) "
    "OUTPUT INSERTED.id, INSERTED.name, INSERTED.owner_id, INSERTED.created_at, INSERTED.updated_at INTO @o "
    "VALUES (?, ?); SELECT * FROM @o;"
)
_GET_SCOPED = "SELECT TOP (1) * FROM orgs WHERE id = ? AND owner_id = ?"


def create_org(db: Db, *, name: str, owner_id: str) -> dict[str, Any]:
    row = db.query_one(_INSERT, (name, owner_id))
    if row is None:
        raise RuntimeError("Failed to create org")
    return row


def get_org_scoped(db: Db, *, org_id: str, owner_id: str) -> Optional[dict[str, Any]]:
    """Fetch an org, scoped to its owner (id + owner_id together)."""
    return db.query_one(_GET_SCOPED, (org_id, owner_id))
