"""All Supabase queries for the `idempotency_keys` table."""
from app.core import db


def get_idempotency_record(key: str, user_id: str) -> dict | None:
    client = db.get_client()
    resp = (
        client.table("idempotency_keys")
        .select("*")
        .eq("key", key)
        .eq("user_id", user_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


def create_idempotency_record(
    key: str, user_id: str, response_body: dict, status_code: int
) -> dict:
    client = db.get_client()
    payload = {
        "key": key,
        "user_id": user_id,
        "response_body": response_body,
        "status_code": status_code,
    }
    resp = client.table("idempotency_keys").insert(payload).execute()
    return resp.data[0]
