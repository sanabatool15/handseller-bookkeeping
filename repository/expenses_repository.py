"""Expenses repository. Every read/update/delete filters by id AND org_id together."""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from supabase import Client

from repository.base import unwrap_single


def create_expense(db: Client, *, org_id: str, created_by: str, amount: float, category: str, voucher_reference: str | None, description: str | None) -> dict[str, Any]:
    resp = (
        db.table("expenses")
        .insert(
            {
                "org_id": org_id,
                "created_by": created_by,
                "amount": amount,
                "category": category,
                "voucher_reference": voucher_reference,
                "description": description,
                # Explicit default (mirrors the column's DB default) so the
                # value is deterministic regardless of DB-side defaults.
                "expense_date": dt.date.today().isoformat(),
            }
        )
        .execute()
    )
    row = unwrap_single(resp.data)
    if row is None:
        raise RuntimeError("Failed to create expense")
    return row


def list_expenses(db: Client, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    resp = (
        db.table("expenses")
        .select("*")
        .eq("org_id", org_id)
        .order("expense_date", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data or []


def get_expense_scoped(db: Client, *, expense_id: str, org_id: str) -> Optional[dict[str, Any]]:
    resp = db.table("expenses").select("*").eq("id", expense_id).eq("org_id", org_id).limit(1).execute()
    return unwrap_single(resp.data)


def update_expense_scoped(db: Client, *, expense_id: str, org_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    resp = db.table("expenses").update(updates).eq("id", expense_id).eq("org_id", org_id).execute()
    return unwrap_single(resp.data)


def delete_expense_scoped(db: Client, *, expense_id: str, org_id: str) -> bool:
    resp = db.table("expenses").delete().eq("id", expense_id).eq("org_id", org_id).execute()
    return bool(resp.data)


def sum_expenses_for_month(db: Client, *, org_id: str, year: int, month: int) -> float:
    start = f"{year:04d}-{month:02d}-01"
    end_month = month + 1 if month < 12 else 1
    end_year = year if month < 12 else year + 1
    end = f"{end_year:04d}-{end_month:02d}-01"
    resp = (
        db.table("expenses")
        .select("amount")
        .eq("org_id", org_id)
        .gte("expense_date", start)
        .lt("expense_date", end)
        .execute()
    )
    return sum(float(r["amount"]) for r in (resp.data or []))
