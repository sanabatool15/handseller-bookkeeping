"""Small helper around supabase-py's table query builder for simple CRUD.

Not a full ORM — just enough shared logic so each router stays short.
"""

from typing import Any

from fastapi import HTTPException
from supabase import Client


def list_rows(
    db: Client,
    table: str,
    *,
    limit: int = 100,
    offset: int = 0,
    order_by: str = "created_at",
    descending: bool = True,
) -> list[dict[str, Any]]:
    query = db.table(table).select("*").order(order_by, desc=descending)
    query = query.range(offset, offset + limit - 1)
    result = query.execute()
    return result.data or []


def get_row(db: Client, table: str, row_id: str) -> dict[str, Any]:
    result = db.table(table).select("*").eq("id", row_id).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail=f"{table[:-1]} not found")
    return result.data[0]


def create_row(db: Client, table: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = db.table(table).insert(payload).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail=f"Failed to create {table[:-1]}")
    return result.data[0]


def update_row(
    db: Client, table: str, row_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    payload = {k: v for k, v in payload.items() if v is not None}
    if not payload:
        return get_row(db, table, row_id)
    result = db.table(table).update(payload).eq("id", row_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail=f"{table[:-1]} not found")
    return result.data[0]


def delete_row(db: Client, table: str, row_id: str) -> None:
    result = db.table(table).delete().eq("id", row_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail=f"{table[:-1]} not found")
