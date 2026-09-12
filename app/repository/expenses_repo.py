"""Repository functions for the `expenses` table. Only Supabase queries live here."""
from datetime import date

from app.db.client import get_client


def create_expense(org_id: str, amount: float, category: str, expense_date: date) -> dict:
    client = get_client()
    response = (
        client.table("expenses")
        .insert(
            {
                "org_id": org_id,
                "amount": float(amount),
                "category": category,
                "expense_date": expense_date.isoformat(),
            }
        )
        .execute()
    )
    return response.data[0]


def get_expense_by_id(expense_id: str, org_id: str) -> dict | None:
    client = get_client()
    response = (
        client.table("expenses")
        .select("*")
        .eq("id", expense_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def list_expenses_for_org(
    org_id: str, start_date: date | None = None, end_date: date | None = None
) -> list[dict]:
    client = get_client()
    query = client.table("expenses").select("*").eq("org_id", org_id)
    if start_date is not None:
        query = query.gte("expense_date", start_date.isoformat())
    if end_date is not None:
        query = query.lte("expense_date", end_date.isoformat())
    response = query.order("expense_date", desc=True).execute()
    return response.data or []
