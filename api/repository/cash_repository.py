"""Cash repository (SQL Server / T-SQL): read-only views of cash_accounts / cash_ledger.

Writes happen ONLY inside the stored procedures (usp_RecordSale / usp_VoidSale), in the same transaction as the
sale, so the balance can never disagree with the sales. Every statement filters by org_id."""
from __future__ import annotations

from typing import Any

from core.db import Db
from repository.base import clamp_page

_BALANCE = "SELECT TOP (1) balance, updated_at FROM cash_accounts WHERE org_id = ?"
_LEDGER = (
    "SELECT id, org_id, entry_type, amount, ref_type, ref_id, balance_after, entry_date, created_by, created_at "
    "FROM cash_ledger WHERE org_id = ? "
    "ORDER BY created_at DESC, id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
)


def get_balance(db: Db, *, org_id: str) -> dict[str, Any]:
    """{balance, updated_at}; an org that never sold anything has no row yet => 0.0 / None."""
    row = db.query_one(_BALANCE, (org_id,))
    if row is None:
        return {"balance": 0.0, "updated_at": None}
    return {"balance": float(row["balance"]), "updated_at": row["updated_at"]}


def list_ledger(db: Db, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    limit, offset = clamp_page(limit, offset)
    return db.query(_LEDGER, (org_id, offset, limit))
