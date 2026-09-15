from __future__ import annotations

from typing import Any, Optional

from supabase import Client

from repository.base import unwrap_single


def create_org(db: Client, *, name: str, owner_id: str) -> dict[str, Any]:
    resp = db.table("orgs").insert({"name": name, "owner_id": owner_id}).execute()
    row = unwrap_single(resp.data)
    if row is None:
        raise RuntimeError("Failed to create org")
    return row


def get_org_scoped(db: Client, *, org_id: str, owner_id: str) -> Optional[dict[str, Any]]:
    """Fetch an org, scoped to its owner (id + owner_id together)."""
    resp = db.table("orgs").select("*").eq("id", org_id).eq("owner_id", owner_id).limit(1).execute()
    return unwrap_single(resp.data)
