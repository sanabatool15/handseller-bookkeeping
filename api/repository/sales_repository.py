"""Sales repository (SQL Server / T-SQL). Every read/update/delete filters by id AND org_id in the same statement."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional

from core.db import Db
from repository.base import clamp_page, month_range

# sales has an AFTER UPDATE trigger => OUTPUT must go INTO a table variable (SQL Server error 334),
# so every write does: DECLARE @o TABLE; <DML> OUTPUT ... INTO @o; SELECT * FROM @o.
_OUT_DECL = (
    "SET NOCOUNT ON; "
    "DECLARE @o TABLE (id uniqueidentifier, org_id uniqueidentifier, created_by uniqueidentifier, "
    "amount decimal(14,2), category nvarchar(100), customer_name nvarchar(200), description nvarchar(max), "
    "sale_date date, customer_id uniqueidentifier, created_at datetimeoffset, updated_at datetimeoffset); "
)
_OUT_COLS = (
    "OUTPUT INSERTED.id, INSERTED.org_id, INSERTED.created_by, INSERTED.amount, INSERTED.category, "
    "INSERTED.customer_name, INSERTED.description, INSERTED.sale_date, INSERTED.customer_id, INSERTED.created_at, INSERTED.updated_at INTO @o "
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
# statement fully static: no SQL is built from the keys of `updates`. customer_id is the exception: a PRESENT
# key (even None) is written, so a sale can be unlinked from its customer (flag 1 = set, 0 = leave).
_UPDATE = (
    _OUT_DECL
    + "UPDATE sales SET amount = CASE WHEN EXISTS (SELECT 1 FROM sale_items WHERE sale_items.sale_id = sales.id AND sale_items.org_id = ?) "
    + "THEN amount ELSE COALESCE(?, amount) END, category = COALESCE(?, category), "
    + "customer_name = COALESCE(?, customer_name), description = COALESCE(?, description), "
    + "customer_id = CASE WHEN ? = 1 THEN CAST(? AS uniqueidentifier) ELSE customer_id END "
    + _OUT_COLS
    + "WHERE id = ? AND org_id = ?; SELECT * FROM @o;"
)
_SUM_MONTH = (
    "SELECT COALESCE(SUM(amount), 0) AS total FROM sales "
    "WHERE org_id = ? AND sale_date >= ? AND sale_date < ?"
)
_SUM_BY_CATEGORY = (
    "SELECT category, SUM(amount) AS total FROM sales "
    "WHERE org_id = ? AND sale_date >= ? AND sale_date < ? GROUP BY category"
)
_UPDATABLE = ("amount", "category", "customer_name", "description", "customer_id")

# Items of ONE sale / of many sales (ids passed as a JSON array, so the statement stays static). product_name via a
# join that is scoped by org_id on both tables.
_ITEM_COLS = (
    "SELECT si.id, si.org_id, si.sale_id, si.product_id, p.name AS product_name, si.quantity, si.unit_price, "
    "si.line_total, si.created_at, si.updated_at "
    "FROM sale_items si JOIN products p ON p.id = si.product_id AND p.org_id = si.org_id "
)
_ITEMS_FOR_SALE = _ITEM_COLS + "WHERE si.sale_id = ? AND si.org_id = ? ORDER BY si.created_at, si.id"
_ITEMS_FOR_SALES = (
    _ITEM_COLS
    + "WHERE si.org_id = ? AND si.sale_id IN (SELECT CAST(j.value AS uniqueidentifier) FROM OPENJSON(?) AS j) "
    + "ORDER BY si.created_at, si.id"
)

# EXEC the stored procedures in ONE batch and SELECT the OUTPUT values back (pyodbc has no OUTPUT-parameter API).
# The procedures own their transaction logic (api/specs/15-transactions-and-concurrency.md).
_RECORD_SALE = (
    "SET NOCOUNT ON; "
    "DECLARE @sale_id uniqueidentifier, @total decimal(14,2), @status nvarchar(20), @message nvarchar(400), "
    "@error_number int, @skipped nvarchar(max); "
    "EXEC dbo.usp_RecordSale @org_id = ?, @created_by = ?, @customer_id = ?, @customer_name = ?, @category = ?, "
    "@description = ?, @amount = ?, @items = ?, @skip_invalid_items = ?, "
    "@sale_id = @sale_id OUTPUT, @total = @total OUTPUT, @status = @status OUTPUT, @message = @message OUTPUT, "
    "@error_number = @error_number OUTPUT, @skipped_items = @skipped OUTPUT; "
    "SELECT @sale_id AS sale_id, @total AS total, @status AS status, @message AS message, "
    "@error_number AS error_number, @skipped AS skipped_items;"
)
_VOID_SALE = (
    "SET NOCOUNT ON; "
    "DECLARE @status nvarchar(20), @message nvarchar(400), @error_number int; "
    "EXEC dbo.usp_VoidSale @org_id = ?, @sale_id = ?, @voided_by = ?, "
    "@status = @status OUTPUT, @message = @message OUTPUT, @error_number = @error_number OUTPUT; "
    "SELECT @status AS status, @message AS message, @error_number AS error_number;"
)
# error numbers raised by the procedures themselves (business outcomes, not engine errors)
BUSINESS_ERRORS = frozenset({50001, 50002, 50003, 50004, 50005, 50006})


class ProcedureError(RuntimeError):
    """The stored procedure rolled back because of an ENGINE error (deadlock 1205, constraint 547, ...).

    The text always contains the error number so core.db.is_deadlock() recognises a deadlock victim."""

    def __init__(self, error_number: int | None, message: str | None):
        self.error_number = error_number
        super().__init__(f"stored procedure failed with error {error_number}: {message}")


def _money(amount: float) -> Decimal:
    return Decimal(str(round(float(amount), 2)))


def _list_items(db: Db, *, org_id: str, sale_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {sid: [] for sid in sale_ids}
    if not sale_ids:
        return out
    for item in db.query(_ITEMS_FOR_SALES, (org_id, json.dumps(sale_ids))):
        out.setdefault(item["sale_id"], []).append(item)
    return out


def list_sales(db: Db, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Sales (newest first), each with its `items` list (empty for quick sales)."""
    limit, offset = clamp_page(limit, offset)
    sales = db.query(_LIST, (org_id, offset, limit))
    items = _list_items(db, org_id=org_id, sale_ids=[s["id"] for s in sales])
    for sale in sales:
        sale["items"] = items.get(sale["id"], [])
    return sales


def list_sales_for_month(db: Db, *, org_id: str, year: int, month: int) -> list[dict[str, Any]]:
    start, end = month_range(year, month)
    return db.query(_LIST_MONTH, (org_id, start, end))


def get_sale_scoped(db: Db, *, sale_id: str, org_id: str) -> Optional[dict[str, Any]]:
    sale = db.query_one(_GET_SCOPED, (sale_id, org_id))
    if sale is None:
        return None
    sale["items"] = db.query(_ITEMS_FOR_SALE, (sale_id, org_id))
    return sale


def update_sale_scoped(db: Db, *, sale_id: str, org_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Metadata update. The amount of a sale WITH line items is never changed by this statement (see _UPDATE)."""
    unknown = set(updates) - set(_UPDATABLE)
    if unknown:
        raise ValueError(f"cannot update columns: {sorted(unknown)}")
    amount = updates.get("amount")
    params = (
        org_id,
        None if amount is None else _money(amount),
        updates.get("category"),
        updates.get("customer_name"),
        updates.get("description"),
        1 if "customer_id" in updates else 0,
        updates.get("customer_id"),
        sale_id,
        org_id,
    )
    row = db.query_one(_UPDATE, params)
    if row is None:
        return None
    row["items"] = db.query(_ITEMS_FOR_SALE, (sale_id, org_id))
    return row


def record_sale(
    db: Db, *, org_id: str, created_by: str, customer_id: str | None, customer_name: str | None, category: str,
    description: str | None, amount: float | None, items: list[dict[str, Any]] | None, skip_invalid_items: bool,
) -> dict[str, Any]:
    """Run dbo.usp_RecordSale. Returns {status, message, error_number, skipped_items, sale}.

    `sale` is the committed sale with its items (read back scoped by org_id) or None when rolled back for a
    business reason (error_number 50001 stock / 50002 product / 50003 validation / 50004 customer / 50005 org).
    An ENGINE error (e.g. deadlock 1205) rolls the connection back and raises ProcedureError so the caller's
    deadlock-retry wrapper can run the whole unit of work again."""
    items_json = json.dumps(items) if items else None
    try:
        row = db.query_one(_RECORD_SALE, (
            org_id, created_by, customer_id, customer_name, category, description,
            None if amount is None else _money(amount), items_json, 1 if skip_invalid_items else 0,
        ))
    except Exception:
        db.rollback()  # e.g. a deadlock raised by the driver itself: leave a clean connection for the retry
        raise
    if row is None:
        db.rollback()
        raise ProcedureError(None, "usp_RecordSale returned no result")
    status = row["status"]
    if status == "rolled_back" and row["error_number"] not in BUSINESS_ERRORS:
        db.rollback()  # clean slate for a retry; the procedure already undid its own work
        raise ProcedureError(row["error_number"], row["message"])
    outcome: dict[str, Any] = {
        "status": status, "message": row["message"], "error_number": row["error_number"],
        "skipped_items": json.loads(row["skipped_items"]) if row.get("skipped_items") else [], "sale": None,
    }
    if status in ("committed", "partial"):
        outcome["sale"] = get_sale_scoped(db, sale_id=row["sale_id"], org_id=org_id)
    return outcome


def void_sale(db: Db, *, org_id: str, sale_id: str, voided_by: str | None) -> dict[str, Any]:
    """Run dbo.usp_VoidSale. Returns {status: 'voided'|'not_found', message}; engine errors raise ProcedureError."""
    try:
        row = db.query_one(_VOID_SALE, (org_id, sale_id, voided_by))
    except Exception:
        db.rollback()
        raise
    if row is None or row["status"] == "rolled_back":
        db.rollback()
        raise ProcedureError(row["error_number"] if row else None, row["message"] if row else "no result")
    return {"status": row["status"], "message": row["message"]}


def sum_sales_for_month(db: Db, *, org_id: str, year: int, month: int) -> float:
    start, end = month_range(year, month)
    row = db.query_one(_SUM_MONTH, (org_id, start, end))
    return float(row["total"]) if row else 0.0


def sum_sales_by_category_for_month(db: Db, *, org_id: str, year: int, month: int) -> dict[str, float]:
    """Returns {category: total_amount} for the given org/month, summed in SQL (GROUP BY)."""
    start, end = month_range(year, month)
    rows = db.query(_SUM_BY_CATEGORY, (org_id, start, end))
    return {r["category"] or "uncategorized": float(r["total"]) for r in rows}
