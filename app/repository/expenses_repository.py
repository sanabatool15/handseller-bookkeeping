"""All Supabase queries for the `expenses` table. Every read/update/delete
filters by BOTH id and org_id simultaneously (structural multi-tenancy).
"""
from app.core import db


def create_expense(
    org_id: str,
    user_id: str,
    amount: float,
    category: str,
    expense_date: str,
    description: str | None = None,
) -> dict:
    client = db.get_client()
    payload = {
        "org_id": org_id,
        "user_id": user_id,
        "amount": amount,
        "category": category,
        "description": description,
        "expense_date": expense_date,
    }
    resp = client.table("expenses").insert(payload).execute()
    return resp.data[0]


def get_expense_scoped(expense_id: str, org_id: str) -> dict | None:
    client = db.get_client()
    resp = (
        client.table("expenses")
        .select("*")
        .eq("id", expense_id)
        .eq("org_id", org_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


def list_expenses_for_period(org_id: str, start_date: str, end_date: str) -> list[dict]:
    client = db.get_client()
    resp = (
        client.table("expenses")
        .select("*")
        .eq("org_id", org_id)
        .gte("expense_date", start_date)
        .lte("expense_date", end_date)
        .execute()
    )
    return resp.data or []


def list_recent_expenses(org_id: str, limit: int = 20) -> list[dict]:
    client = db.get_client()
    resp = (
        client.table("expenses")
        .select("*")
        .eq("org_id", org_id)
        .order("expense_date", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def delete_expense_scoped(expense_id: str, org_id: str) -> bool:
    client = db.get_client()
    resp = (
        client.table("expenses")
        .delete()
        .eq("id", expense_id)
        .eq("org_id", org_id)
        .execute()
    )
    return bool(resp.data)
