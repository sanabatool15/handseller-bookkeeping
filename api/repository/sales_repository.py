"""Sales repository. Every read/update/delete filters by id AND org_id together."""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from supabase import Client

from repository.base import unwrap_single


def create_sale(db: Client, *, org_id: str, created_by: str, amount: float, category: str, description: str | None, customer_name: str | None) -> dict[str, Any]:
    resp = (
        db.table("sales")
        .insert(
            {
                "org_id": org_id,
                "created_by": created_by,
                "amount": amount,
                "category": category,
                "description": description,
                "customer_name": customer_name,
                # Explicit default (mirrors the column's DB default) so the
                # value is deterministic regardless of DB-side defaults.
                "sale_date": dt.date.today().isoformat(),
            }
        )
        .execute()
    )
    row = unwrap_single(resp.data)
    if row is None:
        raise RuntimeError("Failed to create sale")
    return row


def list_sales(db: Client, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    resp = (
        db.table("sales")
        .select("*")
        .eq("org_id", org_id)
        .order("sale_date", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data or []


def get_sale_scoped(db: Client, *, sale_id: str, org_id: str) -> Optional[dict[str, Any]]:
    resp = db.table("sales").select("*").eq("id", sale_id).eq("org_id", org_id).limit(1).execute()
    return unwrap_single(resp.data)


def update_sale_scoped(db: Client, *, sale_id: str, org_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    resp = db.table("sales").update(updates).eq("id", sale_id).eq("org_id", org_id).execute()
    return unwrap_single(resp.data)


def delete_sale_scoped(db: Client, *, sale_id: str, org_id: str) -> bool:
    resp = db.table("sales").delete().eq("id", sale_id).eq("org_id", org_id).execute()
    return bool(resp.data)


def sum_sales_for_month(db: Client, *, org_id: str, year: int, month: int) -> float:
    start = f"{year:04d}-{month:02d}-01"
    end_month = month + 1 if month < 12 else 1
    end_year = year if month < 12 else year + 1
    end = f"{end_year:04d}-{end_month:02d}-01"
    resp = (
        db.table("sales")
        .select("amount")
        .eq("org_id", org_id)
        .gte("sale_date", start)
        .lt("sale_date", end)
        .execute()
    )
    return sum(float(r["amount"]) for r in (resp.data or []))


def sum_sales_by_category_for_month(db: Client, *, org_id: str, year: int, month: int) -> dict[str, float]:
    """Returns {category: total_amount} for the given org/month. Scoped by org_id."""
    start = f"{year:04d}-{month:02d}-01"
    end_month = month + 1 if month < 12 else 1
    end_year = year if month < 12 else year + 1
    end = f"{end_year:04d}-{end_month:02d}-01"
    resp = (
        db.table("sales")
        .select("category,amount")
        .eq("org_id", org_id)
        .gte("sale_date", start)
        .lt("sale_date", end)
        .execute()
    )
    totals: dict[str, float] = {}
    for row in resp.data or []:
        category = row.get("category") or "uncategorized"
        totals[category] = totals.get(category, 0.0) + float(row["amount"])
    return totals
