"""All Supabase queries for the `sales` table. Every read/update/delete
filters by BOTH id and org_id simultaneously (structural multi-tenancy) —
never check-then-fetch.
"""
from app.core import db


def create_sale(
    org_id: str,
    user_id: str,
    amount: float,
    sale_date: str,
    voucher_reference: str | None = None,
) -> dict:
    client = db.get_client()
    payload = {
        "org_id": org_id,
        "user_id": user_id,
        "amount": amount,
        "sale_date": sale_date,
        "voucher_reference": voucher_reference,
    }
    resp = client.table("sales").insert(payload).execute()
    return resp.data[0]


def get_sale_scoped(sale_id: str, org_id: str) -> dict | None:
    client = db.get_client()
    resp = (
        client.table("sales")
        .select("*")
        .eq("id", sale_id)
        .eq("org_id", org_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


def list_sales_for_period(org_id: str, start_date: str, end_date: str) -> list[dict]:
    client = db.get_client()
    resp = (
        client.table("sales")
        .select("*")
        .eq("org_id", org_id)
        .gte("sale_date", start_date)
        .lte("sale_date", end_date)
        .execute()
    )
    return resp.data or []


def list_recent_sales(org_id: str, limit: int = 20) -> list[dict]:
    client = db.get_client()
    resp = (
        client.table("sales")
        .select("*")
        .eq("org_id", org_id)
        .order("sale_date", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def delete_sale_scoped(sale_id: str, org_id: str) -> bool:
    client = db.get_client()
    resp = (
        client.table("sales")
        .delete()
        .eq("id", sale_id)
        .eq("org_id", org_id)
        .execute()
    )
    return bool(resp.data)
