"""users table access (SQL Server / T-SQL via core.db.Db)."""
from __future__ import annotations

from typing import Any, Optional

from core.db import Db

# Login has to find a user BEFORE any org is known, so this one lookup is by the
# UNIQUE email only. It is the single deliberate exception to "always scope by org_id".
_GET_BY_EMAIL = (
    "/* allow-no-org: login/registration lookup by unique email, no org known yet */ "
    "SELECT TOP (1) * FROM users WHERE email = ?"
)
_GET_SCOPED = "SELECT TOP (1) * FROM users WHERE id = ? AND org_id = ?"
# NOTE: users has an AFTER UPDATE trigger, and SQL Server rejects `OUTPUT` without `INTO` on a
# table that has enabled triggers (error 334). So we OUTPUT ... INTO a table variable and SELECT it.
_OUT_DECL = (
    "SET NOCOUNT ON; "
    "DECLARE @o TABLE (id uniqueidentifier, org_id uniqueidentifier, email nvarchar(320), "
    "full_name nvarchar(200), hashed_password nvarchar(255), role nvarchar(20), "
    "created_at datetimeoffset, updated_at datetimeoffset); "
)
_OUT_COLS = (
    "OUTPUT INSERTED.id, INSERTED.org_id, INSERTED.email, INSERTED.full_name, "
    "INSERTED.hashed_password, INSERTED.role, INSERTED.created_at, INSERTED.updated_at INTO @o "
)
_INSERT = (
    _OUT_DECL
    + "INSERT INTO users (email, hashed_password, full_name, org_id, role) "
    + _OUT_COLS
    + "VALUES (?, ?, ?, ?, ?); SELECT * FROM @o;"
)
# Only links a user that has no org yet; org_id appears in the same statement as id.
_SET_ORG = _OUT_DECL + "UPDATE users SET org_id = ? " + _OUT_COLS + "WHERE id = ? AND org_id IS NULL; SELECT * FROM @o;"


def get_user_by_email(db: Db, email: str) -> Optional[dict[str, Any]]:
    return db.query_one(_GET_BY_EMAIL, (email,))


def get_user_by_id_scoped(db: Db, *, user_id: str, org_id: str) -> Optional[dict[str, Any]]:
    """Fetch a user, but only if they belong to the given org (id + org_id together)."""
    return db.query_one(_GET_SCOPED, (user_id, org_id))


def create_user(db: Db, *, email: str, hashed_password: str, full_name: str | None, org_id: str | None, role: str = "member") -> dict[str, Any]:
    """Insert a user. Raises DuplicateRecordError (repository.base) if the email exists."""
    row = db.query_one(_INSERT, (email, hashed_password, full_name, org_id, role))
    if row is None:
        raise RuntimeError("Failed to create user")
    return row


def set_user_org(db: Db, *, user_id: str, org_id: str) -> dict[str, Any]:
    """Link a freshly created (org-less) user to its org. Used by registration."""
    row = db.query_one(_SET_ORG, (org_id, user_id))
    if row is None:
        raise RuntimeError("Failed to link user to org")
    return row
