"""Customers repository (SQL Server / T-SQL). Every read/update/delete filters by id AND org_id in the same statement."""
from __future__ import annotations

from typing import Any, Optional

from core.db import Db
from repository.base import clamp_page

# customers has an AFTER UPDATE trigger => OUTPUT must go INTO a table variable (SQL Server error 334).
_OUT_DECL = (
    "SET NOCOUNT ON; "
    "DECLARE @o TABLE (id uniqueidentifier, org_id uniqueidentifier, created_by uniqueidentifier, "
    "name nvarchar(200), phone nvarchar(32), email nvarchar(320), address nvarchar(500), notes nvarchar(1000), "
    "created_at datetimeoffset, updated_at datetimeoffset); "
)
_OUT_COLS = (
    "OUTPUT INSERTED.id, INSERTED.org_id, INSERTED.created_by, INSERTED.name, INSERTED.phone, INSERTED.email, "
    "INSERTED.address, INSERTED.notes, INSERTED.created_at, INSERTED.updated_at INTO @o "
)
_INSERT = (
    _OUT_DECL
    + "INSERT INTO customers (org_id, created_by, name, phone, email, address, notes) "
    + _OUT_COLS
    + "VALUES (?, ?, ?, ?, ?, ?, ?); SELECT * FROM @o;"
)
_LIST = (
    "SELECT * FROM customers WHERE org_id = ? "
    "ORDER BY name, id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)
# Prefix search on name OR phone. The pattern is a bound parameter whose LIKE wildcards were escaped with
# backslash (see _like_prefix), so user input can never act as a wildcard.
_LIST_SEARCH = (
    "SELECT * FROM customers WHERE org_id = ? AND (name LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\') "
    "ORDER BY name, id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)
_GET_SCOPED = "SELECT TOP (1) * FROM customers WHERE id = ? AND org_id = ?"
# name: never NULL (COALESCE). The four optional fields can be CLEARED: a (flag, value) pair per field,
# flag 1 = "set to value (maybe NULL)", 0 = "leave as is". The statement stays fully static.
_UPDATE = (
    _OUT_DECL
    + "UPDATE customers SET name = COALESCE(?, name), "
    + "phone = CASE WHEN ? = 1 THEN ? ELSE phone END, "
    + "email = CASE WHEN ? = 1 THEN ? ELSE email END, "
    + "address = CASE WHEN ? = 1 THEN ? ELSE address END, "
    + "notes = CASE WHEN ? = 1 THEN ? ELSE notes END "
    + _OUT_COLS
    + "WHERE id = ? AND org_id = ?; SELECT * FROM @o;"
)
# Refuses (0 rows) when the customer still has sales; the NOT EXISTS is in the same statement as the delete,
# so there is no check-then-delete window (a sale inserted concurrently is caught by FK_sales_customer, error 547).
_DELETE = (
    "DELETE FROM customers WHERE id = ? AND org_id = ? "
    "AND NOT EXISTS (SELECT 1 FROM sales WHERE sales.customer_id = customers.id AND sales.org_id = ?)"
)
# org_id is applied to BOTH tables; LEFT JOIN so a customer without sales yields 0 / 0 / NULL.
_SUMMARY = (
    "SELECT c.id, c.org_id, c.created_by, c.name, c.phone, c.email, c.address, c.notes, c.created_at, c.updated_at, "
    "COALESCE(SUM(s.amount), 0) AS total_sales, COUNT(s.id) AS sale_count, MAX(s.sale_date) AS last_sale_date "
    "FROM customers c LEFT JOIN sales s ON s.customer_id = c.id AND s.org_id = c.org_id AND s.org_id = ? "
    "WHERE c.id = ? AND c.org_id = ? "
    "GROUP BY c.id, c.org_id, c.created_by, c.name, c.phone, c.email, c.address, c.notes, c.created_at, c.updated_at"
)
_UPDATABLE = ("name", "phone", "email", "address", "notes")
_CLEARABLE = ("phone", "email", "address", "notes")
_SUMMARY_COLS = ("total_sales", "sale_count", "last_sale_date")


def _like_prefix(term: str) -> str:
    """Escape LIKE wildcards (\\ % _ [) with backslash and append % => literal prefix match."""
    out = []
    for ch in term:
        out.append("\\" + ch if ch in "\\%_[" else ch)
    return "".join(out) + "%"


def create_customer(db: Db, *, org_id: str, created_by: str, name: str, phone: str | None, email: str | None,
                    address: str | None, notes: str | None) -> dict[str, Any]:
    row = db.query_one(_INSERT, (org_id, created_by, name, phone, email, address, notes))
    if row is None:
        raise RuntimeError("Failed to create customer")
    return row


def list_customers(db: Db, *, org_id: str, limit: int = 100, offset: int = 0, q: str | None = None) -> list[dict[str, Any]]:
    limit, offset = clamp_page(limit, offset)
    if q:
        pattern = _like_prefix(q)
        return db.query(_LIST_SEARCH, (org_id, pattern, pattern, offset, limit))
    return db.query(_LIST, (org_id, offset, limit))


def get_customer_scoped(db: Db, *, customer_id: str, org_id: str) -> Optional[dict[str, Any]]:
    return db.query_one(_GET_SCOPED, (customer_id, org_id))


def update_customer_scoped(db: Db, *, customer_id: str, org_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    """`name` None/absent = keep. For phone/email/address/notes a PRESENT key (even None) is written."""
    unknown = set(updates) - set(_UPDATABLE)
    if unknown:
        raise ValueError(f"cannot update columns: {sorted(unknown)}")
    params: list[Any] = [updates.get("name")]
    for col in _CLEARABLE:
        params += [1 if col in updates else 0, updates.get(col)]
    params += [customer_id, org_id]
    return db.query_one(_UPDATE, tuple(params))


def delete_customer_scoped(db: Db, *, customer_id: str, org_id: str) -> bool:
    """True when deleted. False = no such customer in this org OR it still has sales (callers disambiguate)."""
    return db.execute(_DELETE, (customer_id, org_id, org_id)) > 0


def get_customer_summary_scoped(db: Db, *, customer_id: str, org_id: str) -> Optional[dict[str, Any]]:
    row = db.query_one(_SUMMARY, (org_id, customer_id, org_id))
    if row is None:
        return None
    customer = {k: v for k, v in row.items() if k not in _SUMMARY_COLS}
    return {
        "customer": customer,
        "total_sales": float(row["total_sales"] or 0),
        "sale_count": int(row["sale_count"] or 0),
        "last_sale_date": row["last_sale_date"],
    }
