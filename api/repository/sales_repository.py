"""Sales repository (SQL Server / T-SQL). Every read/update/delete filters by id AND org_id in the same statement."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from core.db import Db
from repository.base import clamp_page, month_range, today_utc

# sales has an AFTER UPDATE trigger => OUTPUT must go INTO a table variable (SQL Server error 334),
# so every write does: DECLARE @o TABLE; <DML> OUTPUT ... INTO @o; SELECT * FROM @o.
_OUT_DECL = (
    "SET NOCOUNT ON; "
    "DECLARE @o TABLE (id uniqueidentifier, org_id uniqueidentifier, created_by uniqueidentifier, "
    "amount decimal(14,2), category nvarchar(100), customer_name nvarchar(200), description nvarchar(max), "
    "sale_date date, created_at datetimeoffset, updated_at datetimeoffset); "
)
_OUT_COLS = (
    "OUTPUT INSERTED.id, INSERTED.org_id, INSERTED.created_by, INSERTED.amount, INSERTED.category, "
    "INSERTED.customer_name, INSERTED.description, INSERTED.sale_date, INSERTED.created_at, INSERTED.updated_at INTO @o "
)
_INSERT = (
    _OUT_DECL
    + "INSERT INTO sales (org_id, created_by, amount, category, customer_name, description, sale_date) "
    + _OUT_COLS
    + "VALUES (?, ?, ?, ?, ?, ?, ?); SELECT * FROM @o;"
)
_LIST = (
    "SELECT * FROM sales WHERE org_id = ? "
    "ORDER BY sale_date DESC, created_at DESC, id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)
_LIST_MONTH = (
    "SELECT * FROM sales WHERE org_id = ? AND sale_date >= ? AND sale_date < ? "
    "ORDER BY sale_date DESC, created_at DESC, id"
)
_GET_SCOPED = "SELECT TOP (1) * FROM sales WHERE id = ? AND org_id = ?"
# Updates never set a column to NULL (the service strips None values), so COALESCE(?, col) keeps the
# statement fully static: no SQL is built from the keys of `updates`.
_UPDATE = (
    _OUT_DECL
    + "UPDATE sales SET amount = COALESCE(?, amount), category = COALESCE(?, category), "
    + "customer_name = COALESCE(?, customer_name), description = COALESCE(?, description) "
    + _OUT_COLS
    + "WHERE id = ? AND org_id = ?; SELECT * FROM @o;"
)
_DELETE = "DELETE FROM sales WHERE id = ? AND org_id = ?"
_SUM_MONTH = (
    "SELECT COALESCE(SUM(amount), 0) AS total FROM sales "
    "WHERE org_id = ? AND sale_date >= ? AND sale_date < ?"
)
_SUM_BY_CATEGORY = (
    "SELECT category, SUM(amount) AS total FROM sales "
    "WHERE org_id = ? AND sale_date >= ? AND sale_date < ? GROUP BY category"
)
_UPDATABLE = ("amount", "category", "customer_name", "description")


def _money(amount: float) -> Decimal:
    return Decimal(str(round(float(amount), 2)))


def create_sale(db: Db, *, org_id: str, created_by: str, amount: float, category: str, description: str | None, customer_name: str | None) -> dict[str, Any]:
    row = db.query_one(_INSERT, (org_id, created_by, _money(amount), category, customer_name, description, today_utc()))
    if row is None:
        raise RuntimeError("Failed to create sale")
    return row


def list_sales(db: Db, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    limit, offset = clamp_page(limit, offset)
    return db.query(_LIST, (org_id, offset, limit))


def list_sales_for_month(db: Db, *, org_id: str, year: int, month: int) -> list[dict[str, Any]]:
    start, end = month_range(year, month)
    return db.query(_LIST_MONTH, (org_id, start, end))


def get_sale_scoped(db: Db, *, sale_id: str, org_id: str) -> Optional[dict[str, Any]]:
    return db.query_one(_GET_SCOPED, (sale_id, org_id))


def update_sale_scoped(db: Db, *, sale_id: str, org_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    unknown = set(updates) - set(_UPDATABLE)
    if unknown:
        raise ValueError(f"cannot update columns: {sorted(unknown)}")
    amount = updates.get("amount")
    params = (
        None if amount is None else _money(amount),
        updates.get("category"),
        updates.get("customer_name"),
        updates.get("description"),
        sale_id,
        org_id,
    )
    return db.query_one(_UPDATE, params)


def delete_sale_scoped(db: Db, *, sale_id: str, org_id: str) -> bool:
    return db.execute(_DELETE, (sale_id, org_id)) > 0


def sum_sales_for_month(db: Db, *, org_id: str, year: int, month: int) -> float:
    start, end = month_range(year, month)
    row = db.query_one(_SUM_MONTH, (org_id, start, end))
    return float(row["total"]) if row else 0.0


def sum_sales_by_category_for_month(db: Db, *, org_id: str, year: int, month: int) -> dict[str, float]:
    """Returns {category: total_amount} for the given org/month, summed in SQL (GROUP BY)."""
    start, end = month_range(year, month)
    rows = db.query(_SUM_BY_CATEGORY, (org_id, start, end))
    return {r["category"] or "uncategorized": float(r["total"]) for r in rows}
