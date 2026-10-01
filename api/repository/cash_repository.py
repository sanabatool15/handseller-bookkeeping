"""Cash repository (SQL Server / T-SQL): views of cash_accounts / cash_ledger plus the amount-adjustment procedure.

Cash is WRITTEN only inside stored procedures (usp_RecordSale / usp_VoidSale / usp_RecordExpense / usp_VoidExpense /
usp_AdjustEntryAmount), in the same transaction as the sale/expense, so the balance can never disagree with the
records. Every statement filters by org_id."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from core.db import Db
from repository.base import call_procedure, clamp_page, month_range

_BALANCE = "SELECT TOP (1) balance, updated_at FROM cash_accounts WHERE org_id = ?"
# Optional filters stay parameterised: `(CAST(? AS <type>) IS NULL OR col <op> ...)` makes each filter a no-op when its
# parameter is NULL, so the statement text is static (no SQL is assembled from the filters). The CAST gives the untyped
# NULL parameter a concrete type.
_LEDGER = (
    "SELECT id, org_id, entry_type, amount, ref_type, ref_id, balance_after, entry_date, created_by, created_at "
    "FROM cash_ledger WHERE org_id = ? "
    "AND (CAST(? AS nvarchar(20)) IS NULL OR entry_type = ?) "
    "AND (CAST(? AS date) IS NULL OR entry_date >= CAST(? AS date)) "
    "AND (CAST(? AS date) IS NULL OR entry_date <= CAST(? AS date)) "
    "ORDER BY created_at DESC, id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)
# Summary of a month, computed by the database: opening balance = everything dated before the month; per entry type the
# net, the money in (positive amounts) and the money out (negative amounts, as a positive number) inside the month.
_SUMMARY_OPENING = "SELECT COALESCE(SUM(amount), 0) AS opening FROM cash_ledger WHERE org_id = ? AND entry_date < ?"
_SUMMARY_BY_TYPE = (
    "SELECT entry_type, SUM(amount) AS net, "
    "SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS total_in, "
    "SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS total_out "
    "FROM cash_ledger WHERE org_id = ? AND entry_date >= ? AND entry_date < ? GROUP BY entry_type"
)
_ADJUST = (
    "SET NOCOUNT ON; "
    "DECLARE @status nvarchar(20), @message nvarchar(400), @error_number int; "
    "EXEC dbo.usp_AdjustEntryAmount @org_id = ?, @ref_type = ?, @ref_id = ?, @new_amount = ?, @adjusted_by = ?, "
    "@status = @status OUTPUT, @message = @message OUTPUT, @error_number = @error_number OUTPUT; "
    "SELECT @status AS status, @message AS message, @error_number AS error_number;"
)


def get_balance(db: Db, *, org_id: str) -> dict[str, Any]:
    """{balance, updated_at}; an org that never posted anything has no row yet => 0.0 / None."""
    row = db.query_one(_BALANCE, (org_id,))
    if row is None:
        return {"balance": 0.0, "updated_at": None}
    return {"balance": float(row["balance"]), "updated_at": row["updated_at"]}


def list_ledger(
    db: Db, *, org_id: str, limit: int = 100, offset: int = 0, entry_type: str | None = None,
    date_from: dt.date | None = None, date_to: dt.date | None = None,
) -> list[dict[str, Any]]:
    """Newest first. Optional filters: entry_type, entry_date >= date_from, entry_date <= date_to (both inclusive)."""
    limit, offset = clamp_page(limit, offset)
    return db.query(_LEDGER, (org_id, entry_type, entry_type, date_from, date_from, date_to, date_to, offset, limit))


def get_month_summary(db: Db, *, org_id: str, year: int, month: int) -> dict[str, Any]:
    """{opening_balance, total_in, total_out, closing_balance, by_type: {entry_type: net}} for one calendar month
    (by entry_date), aggregated by SQL Server (SUM / GROUP BY). A month without rows gives zeros and an empty by_type;
    its closing balance equals the opening balance."""
    start, end = month_range(year, month)
    opening = float(db.query_one(_SUMMARY_OPENING, (org_id, start))["opening"])
    rows = db.query(_SUMMARY_BY_TYPE, (org_id, start, end))
    total_in = sum(float(r["total_in"]) for r in rows)
    total_out = sum(float(r["total_out"]) for r in rows)
    net = sum(float(r["net"]) for r in rows)
    return {
        "opening_balance": round(opening, 2),
        "total_in": round(total_in, 2),
        "total_out": round(total_out, 2),
        "closing_balance": round(opening + net, 2),
        "by_type": {r["entry_type"]: round(float(r["net"]), 2) for r in rows},
    }


def adjust_entry_amount(
    db: Db, *, org_id: str, ref_type: str, ref_id: str, new_amount: float, adjusted_by: str | None,
) -> dict[str, Any]:
    """Run dbo.usp_AdjustEntryAmount: sets the amount of a sale/expense and posts the delta as an 'adjustment' entry.

    Returns {status, message, error_number}; status is 'adjusted' | 'unchanged' | 'not_found' | 'not_allowed'
    (sale with line items) | 'rolled_back' (business validation, error 50003). Engine errors raise ProcedureError."""
    row = call_procedure(
        db, _ADJUST, (org_id, ref_type, ref_id, Decimal(str(round(float(new_amount), 2))), adjusted_by),
        name="usp_AdjustEntryAmount",
    )
    return {"status": row["status"], "message": row["message"], "error_number": row["error_number"]}
