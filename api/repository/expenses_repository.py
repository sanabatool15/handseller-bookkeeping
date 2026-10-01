"""Expenses repository (SQL Server / T-SQL). Every read/update/delete filters by id AND org_id in the same statement."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional

from core.db import Db
from repository.base import call_procedure, clamp_page, month_range

# expenses has an AFTER UPDATE trigger => OUTPUT must go INTO a table variable (SQL Server error 334),
# so every write does: DECLARE @o TABLE; <DML> OUTPUT ... INTO @o; SELECT * FROM @o.
_OUT_DECL = (
    "SET NOCOUNT ON; "
    "DECLARE @o TABLE (id uniqueidentifier, org_id uniqueidentifier, created_by uniqueidentifier, "
    "amount decimal(14,2), category nvarchar(100), voucher_reference nvarchar(200), description nvarchar(max), "
    "expense_date date, created_at datetimeoffset, updated_at datetimeoffset); "
)
_OUT_COLS = (
    "OUTPUT INSERTED.id, INSERTED.org_id, INSERTED.created_by, INSERTED.amount, INSERTED.category, "
    "INSERTED.voucher_reference, INSERTED.description, INSERTED.expense_date, INSERTED.created_at, INSERTED.updated_at INTO @o "
)
_LIST = (
    "SELECT * FROM expenses WHERE org_id = ? "
    "ORDER BY expense_date DESC, created_at DESC, id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)
_LIST_MONTH = (
    "SELECT * FROM expenses WHERE org_id = ? AND expense_date >= ? AND expense_date < ? "
    "ORDER BY expense_date DESC, created_at DESC, id"
)
_GET_SCOPED = "SELECT TOP (1) * FROM expenses WHERE id = ? AND org_id = ?"
# METADATA update only. `amount` is deliberately NOT updatable here (it is part of the cash ledger): it changes only
# through dbo.usp_AdjustEntryAmount (cash_repository.adjust_entry_amount). Updates never set a column to NULL (the
# service strips None values), so COALESCE(?, col) keeps the statement fully static.
_UPDATE = (
    _OUT_DECL
    + "UPDATE expenses SET category = COALESCE(?, category), "
    + "voucher_reference = COALESCE(?, voucher_reference), description = COALESCE(?, description) "
    + _OUT_COLS
    + "WHERE id = ? AND org_id = ?; SELECT * FROM @o;"
)
_SUM_MONTH = (
    "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses "
    "WHERE org_id = ? AND expense_date >= ? AND expense_date < ?"
)
_SUM_BY_CATEGORY = (
    "SELECT category, SUM(amount) AS total FROM expenses "
    "WHERE org_id = ? AND expense_date >= ? AND expense_date < ? GROUP BY category"
)
_UPDATABLE = ("category", "voucher_reference", "description")

# EXEC the stored procedures in ONE batch and SELECT the OUTPUT values back (see sales_repository / specs/15).
_RECORD_EXPENSE = (
    "SET NOCOUNT ON; "
    "DECLARE @expense_id uniqueidentifier, @status nvarchar(20), @message nvarchar(400), @error_number int; "
    "EXEC dbo.usp_RecordExpense @org_id = ?, @created_by = ?, @amount = ?, @category = ?, @voucher_reference = ?, "
    "@description = ?, @expense_date = ?, "
    "@expense_id = @expense_id OUTPUT, @status = @status OUTPUT, @message = @message OUTPUT, "
    "@error_number = @error_number OUTPUT; "
    "SELECT @expense_id AS expense_id, @status AS status, @message AS message, @error_number AS error_number;"
)
_VOID_EXPENSE = (
    "SET NOCOUNT ON; "
    "DECLARE @status nvarchar(20), @message nvarchar(400), @error_number int; "
    "EXEC dbo.usp_VoidExpense @org_id = ?, @expense_id = ?, @voided_by = ?, "
    "@status = @status OUTPUT, @message = @message OUTPUT, @error_number = @error_number OUTPUT; "
    "SELECT @status AS status, @message AS message, @error_number AS error_number;"
)


def _money(amount: float) -> Decimal:
    return Decimal(str(round(float(amount), 2)))


def record_expense(
    db: Db, *, org_id: str, created_by: str, amount: float, category: str, voucher_reference: str | None,
    description: str | None, expense_date: dt.date | None = None,
) -> dict[str, Any]:
    """Run dbo.usp_RecordExpense (expense + cash balance - amount + 'expense' ledger entry, one transaction).

    Returns {status: 'committed'|'rolled_back', message, error_number, expense}; `expense` is the committed row (read back
    scoped by id AND org_id) or None for a business rollback (50003 validation / 50005 org). Engine errors (deadlock, ...)
    raise ProcedureError after a rollback. There is NO plain INSERT path: it would bypass the cash ledger."""
    row = call_procedure(db, _RECORD_EXPENSE, (
        org_id, created_by, _money(amount), category, voucher_reference, description, expense_date,
    ), name="usp_RecordExpense")
    outcome: dict[str, Any] = {"status": row["status"], "message": row["message"], "error_number": row["error_number"], "expense": None}
    if row["status"] == "committed":
        outcome["expense"] = get_expense_scoped(db, expense_id=row["expense_id"], org_id=org_id)
    return outcome


def void_expense(db: Db, *, org_id: str, expense_id: str, voided_by: str | None) -> dict[str, Any]:
    """Run dbo.usp_VoidExpense. Returns {status: 'voided'|'not_found', message}; engine errors raise ProcedureError."""
    row = call_procedure(db, _VOID_EXPENSE, (org_id, expense_id, voided_by), name="usp_VoidExpense")
    return {"status": row["status"], "message": row["message"]}


def list_expenses(db: Db, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    limit, offset = clamp_page(limit, offset)
    return db.query(_LIST, (org_id, offset, limit))


def list_expenses_for_month(db: Db, *, org_id: str, year: int, month: int) -> list[dict[str, Any]]:
    start, end = month_range(year, month)
    return db.query(_LIST_MONTH, (org_id, start, end))


def get_expense_scoped(db: Db, *, expense_id: str, org_id: str) -> Optional[dict[str, Any]]:
    return db.query_one(_GET_SCOPED, (expense_id, org_id))


def update_expense_scoped(db: Db, *, expense_id: str, org_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Metadata update (category, voucher_reference, description). `amount` is rejected (ValueError): it goes through
    cash_repository.adjust_entry_amount so the cash ledger stays consistent."""
    unknown = set(updates) - set(_UPDATABLE)
    if unknown:
        raise ValueError(f"cannot update columns: {sorted(unknown)}")
    params = (
        updates.get("category"),
        updates.get("voucher_reference"),
        updates.get("description"),
        expense_id,
        org_id,
    )
    return db.query_one(_UPDATE, params)


def sum_expenses_for_month(db: Db, *, org_id: str, year: int, month: int) -> float:
    start, end = month_range(year, month)
    row = db.query_one(_SUM_MONTH, (org_id, start, end))
    return float(row["total"]) if row else 0.0


def sum_expenses_by_category_for_month(db: Db, *, org_id: str, year: int, month: int) -> dict[str, float]:
    """Returns {category: total_amount} for the given org/month, summed in SQL (GROUP BY)."""
    start, end = month_range(year, month)
    rows = db.query(_SUM_BY_CATEGORY, (org_id, start, end))
    return {r["category"] or "uncategorized": float(r["total"]) for r in rows}
