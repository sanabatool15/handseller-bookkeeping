"""Repository functions for the `sales` table. Only Supabase queries live here."""
from datetime import date

from app.db.client import get_client


def create_sale(
    org_id: str, amount: float, voucher_reference: str | None, sale_date: date
) -> dict:
    client = get_client()
    response = (
        client.table("sales")
        .insert(
            {
                "org_id": org_id,
                "amount": float(amount),
                "voucher_reference": voucher_reference,
                "sale_date": sale_date.isoformat(),
            }
        )
        .execute()
    )
    return response.data[0]


def get_sale_by_id(sale_id: str, org_id: str) -> dict | None:
    client = get_client()
    response = (
        client.table("sales")
        .select("*")
        .eq("id", sale_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def list_sales_for_org(
    org_id: str, start_date: date | None = None, end_date: date | None = None
) -> list[dict]:
    client = get_client()
    query = client.table("sales").select("*").eq("org_id", org_id)
    if start_date is not None:
        query = query.gte("sale_date", start_date.isoformat())
    if end_date is not None:
        query = query.lte("sale_date", end_date.isoformat())
    response = query.order("sale_date", desc=True).execute()
    return response.data or []
