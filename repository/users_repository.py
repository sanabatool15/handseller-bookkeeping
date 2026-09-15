from __future__ import annotations

from typing import Any, Optional

from supabase import Client

from repository.base import unwrap_single


def get_user_by_email(db: Client, email: str) -> Optional[dict[str, Any]]:
    resp = db.table("users").select("*").eq("email", email).limit(1).execute()
    return unwrap_single(resp.data)


def get_user_by_id_scoped(db: Client, *, user_id: str, org_id: str) -> Optional[dict[str, Any]]:
    """Fetch a user, but only if they belong to the given org (id + org_id together)."""
    resp = db.table("users").select("*").eq("id", user_id).eq("org_id", org_id).limit(1).execute()
    return unwrap_single(resp.data)


def create_user(db: Client, *, email: str, hashed_password: str, full_name: str | None, org_id: str | None, role: str = "member") -> dict[str, Any]:
    resp = (
        db.table("users")
        .insert(
            {
                "email": email,
                "hashed_password": hashed_password,
                "full_name": full_name,
                "org_id": org_id,
                "role": role,
            }
        )
        .execute()
    )
    row = unwrap_single(resp.data)
    if row is None:
        raise RuntimeError("Failed to create user")
    return row
