"""Only this module (and its siblings under repository/) may issue
Supabase queries for expenses. All queries filter by org_id to enforce
tenant isolation at the data-access boundary."""

from datetime import date
from uuid import UUID

from app.db import get_client

TABLE = "expenses"


def create_expense(org_id: UUID, user_id: UUID, data: dict) -> dict:
    payload = {**data, "org_id": str(org_id), "user_id": str(user_id)}
    result = get_client().table(TABLE).insert(payload).execute()
    return result.data[0]


def get_expense_by_id(expense_id: UUID) -> dict | None:
    """Fetch an expense by id, unscoped by org. Callers (services) MUST
    check org ownership themselves before returning/mutating, or use
    get_expense_for_org for a pre-scoped fetch."""
    result = get_client().table(TABLE).select("*").eq("id", str(expense_id)).limit(1).execute()
    return result.data[0] if result.data else None


def get_expense_for_org(expense_id: UUID, org_id: UUID) -> dict | None:
    result = (
        get_client()
        .table(TABLE)
        .select("*")
        .eq("id", str(expense_id))
        .eq("org_id", str(org_id))
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def list_expenses_for_org(org_id: UUID, start: date | None = None, end: date | None = None) -> list[dict]:
    query = get_client().table(TABLE).select("*").eq("org_id", str(org_id))
    if start is not None:
        query = query.gte("expense_date", start.isoformat())
    if end is not None:
        query = query.lte("expense_date", end.isoformat())
    result = query.order("expense_date", desc=True).execute()
    return result.data


def update_expense(expense_id: UUID, org_id: UUID, data: dict) -> dict | None:
    result = (
        get_client()
        .table(TABLE)
        .update(data)
        .eq("id", str(expense_id))
        .eq("org_id", str(org_id))
        .execute()
    )
    return result.data[0] if result.data else None


def delete_expense(expense_id: UUID, org_id: UUID) -> bool:
    result = (
        get_client()
        .table(TABLE)
        .delete()
        .eq("id", str(expense_id))
        .eq("org_id", str(org_id))
        .execute()
    )
    return bool(result.data)
