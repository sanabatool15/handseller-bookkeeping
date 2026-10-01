"""SQL Server helpers shared by the real-infra e2e suites (tests/e2e/prompt-N/conftest.py).

Replaces the old Supabase `db.table(...)` calls in test setup/teardown. Tests are allowed to
write SQL (the layering rule only applies to application code); every statement is
parameterised, table names come from fixed allow-lists, and deletes are scoped by id AND org_id.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from core.clients import get_db_connection

_LATEST = {
    "sales": "SELECT TOP (1) id FROM sales WHERE org_id = ? ORDER BY created_at DESC",
    "expenses": "SELECT TOP (1) id FROM expenses WHERE org_id = ? ORDER BY created_at DESC",
}
_DELETE = {
    "sales": "DELETE FROM sales WHERE id = ? AND org_id = ?",
    "expenses": "DELETE FROM expenses WHERE id = ? AND org_id = ?",
    "agent_jobs": "DELETE FROM agent_jobs WHERE id = ? AND org_id = ?",  # agent_logs cascade
}
_INSERT = {
    "sales": "INSERT INTO sales (id, org_id, created_by, amount, category, description) VALUES (?, ?, ?, ?, ?, ?)",
    "expenses": "INSERT INTO expenses (id, org_id, created_by, amount, category, description) VALUES (?, ?, ?, ?, ?, ?)",
}


def connect():
    """A real SQL Server connection (MSSQL_* settings)."""
    return get_db_connection()


def latest_rows(db, table: str, org_id: str):
    """Newest sales/expenses row of an org, shaped like the old Supabase response (`.data` list)."""
    rows = db.query(_LATEST[table], (org_id,))
    db.commit()  # end the read transaction so later reads see rows other connections committed
    return SimpleNamespace(data=rows)


def insert_ledger_row(db, table: str, row: dict[str, Any]) -> None:
    db.execute(_INSERT[table], (row["id"], row["org_id"], row["created_by"], row["amount"], row["category"], row.get("description")))
    db.commit()


def purge_org(db, org_id: str) -> None:
    """Remove an org and everything hanging off it (SQL Server FKs here do not cascade)."""
    for sql in (
        "DELETE FROM agent_logs WHERE org_id = ?",
        "DELETE FROM agent_jobs WHERE org_id = ?",
        "DELETE FROM sales WHERE org_id = ?",
        "DELETE FROM expenses WHERE org_id = ?",
        "UPDATE orgs SET owner_id = NULL WHERE id = ?",
        "DELETE FROM users WHERE org_id = ?",
        "DELETE FROM orgs WHERE id = ?",
    ):
        db.execute(sql, (org_id,))
    db.commit()


def delete_tracked(db, table: str, record_id: str, org_id: str | None) -> None:
    """Teardown of one tracked row. `orgs` purges the whole org (so tracked children may already be gone)."""
    try:
        if table == "orgs":
            # The tracked record_id of an org is the org id itself.
            purge_org(db, record_id)
        elif table == "users":
            db.execute("UPDATE orgs SET owner_id = NULL WHERE owner_id = ? AND id = ?", (record_id, org_id))
            db.execute("DELETE FROM users WHERE id = ? AND org_id = ?", (record_id, org_id))
            db.commit()
        else:
            db.execute(_DELETE[table], (record_id, org_id))
            db.commit()
    except Exception:
        db.rollback()
        raise
